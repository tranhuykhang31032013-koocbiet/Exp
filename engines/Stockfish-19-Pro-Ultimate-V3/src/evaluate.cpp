/*
  Stockfish, a UCI chess playing engine derived from Glaurung 2.1
  Copyright (C) 2004-2026 The Stockfish developers (see AUTHORS file)

  Stockfish is free software: you can redistribute it and/or modify
  it under the terms of the GNU General Public License as published by
  the Free Software Foundation, either version 3 of the License, or
  (at your option) any later version.

  Stockfish is distributed in the hope that it will be useful,
  but WITHOUT ANY WARRANTY; without even the implied warranty of
  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
  GNU General Public License for more details.

  You should have received a copy of the GNU General Public License
  along with this program.  If not, see <http://www.gnu.org/licenses/>.
*/

#include "evaluate.h"

#include <algorithm>
#include <cassert>
#include <cmath>
#include <cstdlib>
#include <iomanip>
#include <iostream>
#include <memory>
#include <sstream>

#include "misc.h"
#include "nnue/network.h"
#include "nnue/nnue_misc.h"
#include "position.h"
#include "types.h"
#include "uci.h"
#include "nnue/nnue_accumulator.h"

namespace Stockfish {

// Unified, overflow-safe, sign-preserving, symmetric rule50 and fortress dampening:
// 1. Clamps r50 to [0, 100] in 64-bit signed integer arithmetic (preventing 32-bit overflow
//    even on synthetic FENs with r50 up to 32767).
// 2. Applies Stockfish 19's exact linear rule50 dampening:
//      scaled = i64(v) - (i64(v) * clampedR50) / 199
// 3. When fortressDetect is enabled and clampedR50 > 60 (late shuffling), applies a bounded
//    quadratic dampening:
//      excess = clampedR50 - 60   (strictly in [1, 40], excess^2 in [1, 1600])
//      scaled -= (scaled * (excess * excess)) / 6400
//    Maximum additional reduction at r50 = 100 is 1600 / 6400 = 25.0%.
//    Guarantees:
//      - Zero sign inversions: sign(scaled) == sign(v) for all v and r50.
//      - Exact WHITE/BLACK symmetry: f(-v, r50, fd) == -f(v, r50, fd).
//      - Monotonic non-increasing |scaled| as r50 increases in [0, 100].
// Single point of scaling for Dynamic Aggression (FINDING-03 fix).
// Clamps aggressionPct to [50, 150] in 64-bit signed integer arithmetic and scales optimism once.
// Preserves exact upstream Stockfish 19 behavior when aggressionPct == 100.
int Eval::scale_optimism_by_aggression(int optimism, int aggressionPct) noexcept {
    const i64 clampedAgg = std::clamp<i64>(aggressionPct, 50, 150);
    if (clampedAgg == 100)
        return optimism;
    const i64 scaled = (i64(optimism) * clampedAgg) / 100;
    return static_cast<int>(std::clamp<i64>(scaled, -30000, 30000));
}

int Eval::apply_rule50_and_fortress_scaling(int v, int r50, bool fortressDetect) noexcept {
    const i64 clampedR50 = std::clamp<i64>(r50, 0, 100);
    i64       scaled     = i64(v) - (i64(v) * clampedR50) / 199;

    if (fortressDetect && clampedR50 > 60)
    {
        const i64 excess = clampedR50 - 60;
        scaled -= (scaled * (excess * excess)) / 6400;
    }

    return static_cast<int>(scaled);
}

// Evaluate is the evaluator for the outer world. It returns a static evaluation
// of the position from the point of view of the side to move.
Value Eval::evaluate(const Eval::NNUE::Network&     network,
                     const Position&                pos,
                     Eval::NNUE::AccumulatorStack&  accumulators,
                     Eval::NNUE::AccumulatorCaches& caches,
                     int                            optimism,
                     bool                           fortressDetect,
                     int                            aggressionPct) {

    assert(!pos.checkers());

    auto [psqt, positional] = network.evaluate(pos, accumulators, caches);

    Value nnue = psqt + positional;

    // Blend optimism and eval with nnue complexity (exact Stockfish 19 SPSA constants)
    int nnueComplexity = std::abs(psqt - positional);
    optimism += optimism * i64(nnueComplexity) / 476;
    nnue -= nnue * i64(nnueComplexity) / 18236;

    // Single-point Dynamic Aggression scaling (applied once and only here; never pre-scaled in search.cpp)
    if (aggressionPct != 100)
        optimism = scale_optimism_by_aggression(optimism, aggressionPct);

    int material = 534 * pos.count<PAWN>() + pos.non_pawn_material();
    int v        = nnue + (nnue * i64(material) + optimism * i64(7675)) / 91000;

    // Damp down the evaluation when shuffling, with optional bounded fortress detection
    const int r50 = pos.rule50_count();
    if (!fortressDetect && r50 >= 0 && r50 <= 100)
        v -= v * r50 / 199;
    else
        v = apply_rule50_and_fortress_scaling(
          v, r50, fortressDetect && r50 > 60 && pos.non_pawn_material() > 0 && pos.count<PAWN>() <= 8);

    // Guarantee evaluation does not hit the tablebase range
    v = std::clamp(v, VALUE_TB_LOSS_IN_MAX_PLY + 1, VALUE_TB_WIN_IN_MAX_PLY - 1);

    return v;
}

// Like evaluate(), but instead of returning a value, it returns
// a string (suitable for outputting to stdout) that contains the detailed
// descriptions and values of each evaluation term. Useful for debugging.
// Trace scores are from white's point of view
std::string Eval::trace(Position&                  pos,
                        const Eval::NNUE::Network& network,
                        bool                       fortressDetect,
                        int                        aggressionPct,
                        int                        optimismBias) {

    if (pos.checkers())
        return "Final evaluation: none (in check)";

    auto accumulators = std::make_unique<Eval::NNUE::AccumulatorStack>();
    auto caches       = std::make_unique<Eval::NNUE::AccumulatorCaches>(network);

    std::stringstream ss;
    ss << std::showpoint << std::noshowpos << std::fixed << std::setprecision(2);
    ss << '\n' << NNUE::trace(pos, network, *caches) << '\n';

    ss << std::showpoint << std::showpos << std::fixed << std::setprecision(2) << std::setw(15);

    auto [psqt, positional] = network.evaluate(pos, *accumulators, *caches);
    Value v                 = psqt + positional;
    ss << "NNUE evaluation          " << v << " (side to move, internal units)\n";
    v = pos.side_to_move() == WHITE ? v : -v;
    ss << "NNUE evaluation        " << 0.01 * UCIEngine::to_cp(v, pos) << " (white side)\n";

    const int clampedAgg = int(std::clamp<i64>(aggressionPct, 50, 150));
    const int adjOpt     = scale_optimism_by_aggression(optimismBias, aggressionPct);
    const int unitScale  = scale_optimism_by_aggression(100, aggressionPct);
    ss << "Dynamic Aggression       " << clampedAgg << "% (base optimism: " << optimismBias
       << ", adjusted optimism: " << adjOpt << ", unit-100 scale: " << unitScale << ")\n";

    v = evaluate(network, pos, *accumulators, *caches, optimismBias, fortressDetect, aggressionPct);
    v = pos.side_to_move() == WHITE ? v : -v;

    ss << "Final evaluation      ";
    ss << 0.01 * UCIEngine::to_cp(v, pos) << " (white side)";
    ss << " [with scaled NNUE, ...]\n";

    return ss.str();
}

}  // namespace Stockfish
