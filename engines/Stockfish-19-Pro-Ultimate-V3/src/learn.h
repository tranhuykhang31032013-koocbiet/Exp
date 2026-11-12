/*
  Stockfish, a UCI chess playing engine derived from Glaurung 2.1
  Copyright (C) 2004-2026 The Stockfish developers (see AUTHORS file)

  Stockfish 19-Pro Ultimate V2 — Persistent Experience & Self-Learning System
  Strictly distinguishes:
    1. Move Experience Database (experience.bin, SF19EXP2 / SF19EXP1 format)
    2. Temporal-Difference (TD-Lambda) trajectory bootstrapping (finalize_game)
    3. Outcome-based Reinforcement Learning from game results & PGNs (record_outcome, ingest_pgn_file)
    4. Safe Move-Ordering integration (pre-ID root ordering & TT-miss move seeding)
  Never modifies NNUE weights at runtime and never overrides staticEval or post-search bestmove.
*/

#ifndef LEARN_H_INCLUDED
#define LEARN_H_INCLUDED

#include <array>
#include <atomic>
#include <cstdint>
#include <filesystem>
#include <optional>
#include <shared_mutex>
#include <string>
#include <unordered_map>
#include <vector>

#include "types.h"
#include "learned_genome.h"

namespace Stockfish {

inline constexpr std::size_t MAX_EXPERIENCE_ENTRIES = 262144;  // 6 MiB cap (262,144 * 24 bytes)

#pragma pack(push, 1)
struct ExpDiskEntry {
    Key posKey;      // 8 bytes: Zobrist hash of position (little-endian on disk)
    u16 moveRaw;     // 2 bytes: Move::raw()
    i16 score;       // 2 bytes: latest verified deep search evaluation [-30000..30000]
    i16 tdScore;     // 2 bytes: Temporal-Difference / RL learned value [-30000..30000]
    u8  depth;       // 1 byte:  max search depth achieved [1..246]
    u8  winPerf;     // 1 byte:  0..200 (100 = neutral, >100 = winning, <100 = losing)
    u32 gamesCount;  // 4 bytes: number of games this position/move was updated
    u32 checksum;    // 4 bytes: FNV-1a integrity checksum (non-zero in SF19EXP2)
};
#pragma pack(pop)

static_assert(sizeof(ExpDiskEntry) == 24, "ExpDiskEntry must be 24 bytes");

struct TrajectoryStep {
    Key   posKey;
    Color side;
    int   ply;
    Move  move;
    Value score;
    Depth depth;
};

class LearnManager {
   public:
    LearnManager() = default;
    ~LearnManager() noexcept;

    LearnManager(const LearnManager&)            = delete;
    LearnManager& operator=(const LearnManager&) = delete;

    void init(const std::filesystem::path& expPath,
              const std::filesystem::path& binDir,
              bool                         enabled) noexcept;

    void set_enabled(bool enabled) noexcept { isEnabled.store(enabled, std::memory_order_relaxed); }
    bool enabled() const noexcept { return isEnabled.load(std::memory_order_relaxed); }
    bool has_entries() const noexcept { return hasEntries.load(std::memory_order_relaxed); }
    bool may_contain(Key posKey) const noexcept {
        if (!hasEntries.load(std::memory_order_relaxed))
            return false;
        const u64 h1 = (posKey >> 58) & 63ULL;
        const u64 b1 = 1ULL << ((posKey >> 52) & 63ULL);
        const u64 h2 = (posKey >> 46) & 63ULL;
        const u64 b2 = 1ULL << ((posKey >> 40) & 63ULL);
        return (bloomFilter[h1].load(std::memory_order_relaxed) & b1) != 0ULL
            && (bloomFilter[h2].load(std::memory_order_relaxed) & b2) != 0ULL;
    }

    bool load_from_disk(const std::filesystem::path& expPath,
                        const std::filesystem::path& binDir = {}) noexcept;
    bool save_to_disk() const noexcept;

    // Thread-safe value-returning queries (eliminates dangling pointers after lock release)
    std::optional<ExpDiskEntry> probe_move(Key posKey, Move m) const noexcept;
    std::optional<ExpDiskEntry> probe_best(Key posKey, Depth minDepth = 6) const noexcept;
    std::vector<ExpDiskEntry>   probe_all(Key posKey) const noexcept;

    // Harvest top Principal Variation moves (both sides) into experience table
    void record_pv_line(const std::string&       rootFen,
                        bool                     isChess960,
                        int                      rootPly,
                        const std::vector<Move>& pvMoves,
                        Value                    rootScore,
                        Depth                    completedDepth,
                        int                      learningRatePct) noexcept;

    // Record a completed root decision during a game
    void record_step(Key   posKey,
                     Color side,
                     int   ply,
                     Move  bestMove,
                     Value score,
                     Depth depth,
                     int   learningRatePct) noexcept;

    // Finalize current game trajectory (TD-Lambda backward pass) and atomically flush to disk
    void finalize_game(int learningRatePct = 100, std::optional<int> whiteOutcome = std::nullopt) noexcept;

    // Outcome-based RL update (+1 = White win, 0 = Draw, -1 = Black win)
    void record_outcome(int whiteOutcome, int learningRatePct = 100) noexcept;

    // Inject a verified UCI move sequence from startpos for targetColor ('W', 'B', or 'A')
    std::size_t inject_uci_line(char                            targetColor,
                                Depth                           depth,
                                u8                              winPerf,
                                Value                           score,
                                u32                             gamesCount,
                                const std::vector<std::string>& uciMoves,
                                int                             startPly = 0,
                                int                             endPly   = 160) noexcept;

    // Ingest a PGN file for outcome-based Reinforcement Learning (returns number of games ingested)
    std::size_t ingest_pgn_file(const std::filesystem::path& pgnPath,
                                bool                         isChess960      = false,
                                int                          learningRatePct = 100) noexcept;

    // Clear in-memory experience table and trajectory
    void clear() noexcept;

    // Adaptive opponent profiling bonus for optimism (bounded [-15, +15])
    int get_adaptive_optimism_bonus(Color us) const noexcept;
    const LearnedSearchGenome& genome() const noexcept { return activeGenome; }
    bool load_genome_file(const std::filesystem::path& path) noexcept;

    // Omega Time-Bank Controller (saves unused ms on book/forced moves for critical middlegame turns)
    i64  peek_time_bank() const noexcept { return timeBankMs.load(std::memory_order_relaxed); }
    void add_time_bank(i64 deltaMs) noexcept {
        i64 cur = timeBankMs.load(std::memory_order_relaxed);
        i64 nxt = std::clamp<i64>(cur + deltaMs, 0, 60000);
        timeBankMs.store(nxt, std::memory_order_relaxed);
    }
    void reset_time_bank(i64 initMs = 800) noexcept {
        timeBankMs.store(initMs, std::memory_order_relaxed);
    }

    // Summary statistics for UCI info output
    std::string summary_info() const;

    // Compute and verify entry checksum
    static u32  compute_checksum(const ExpDiskEntry& e) noexcept;
    static bool validate_entry(const ExpDiskEntry& e, bool requireChecksum = false) noexcept;

   private:
    void update_entry_locked(Key   posKey,
                             Move  m,
                             Value score,
                             Value tdTarget,
                             Depth depth,
                             int   lrPct,
                             bool  incrementGame) noexcept;

    void flush_trajectory_locked(int lrPct, std::optional<int> whiteOutcome) noexcept;
    bool save_to_disk_locked() const noexcept;

    static std::filesystem::path resolve_writable_path(const std::filesystem::path& requested,
                                                       const std::filesystem::path& binDir) noexcept;

    mutable std::shared_mutex                          mtx;
    std::filesystem::path                              currentPath{"experience.bin"};
    std::filesystem::path                              binaryDir{};
    std::atomic<bool>                                  isEnabled{true};
    std::atomic<bool>                                  hasEntries{false};
    std::array<std::atomic<u64>, 64>                   bloomFilter{};
    void bloom_insert(Key posKey) noexcept {
        const u64 h1 = (posKey >> 58) & 63ULL;
        const u64 b1 = 1ULL << ((posKey >> 52) & 63ULL);
        const u64 h2 = (posKey >> 46) & 63ULL;
        const u64 b2 = 1ULL << ((posKey >> 40) & 63ULL);
        bloomFilter[h1].fetch_or(b1, std::memory_order_relaxed);
        bloomFilter[h2].fetch_or(b2, std::memory_order_relaxed);
    }
    void bloom_clear() noexcept {
        for (auto& w : bloomFilter)
            w.store(0ULL, std::memory_order_relaxed);
    }
    mutable bool                                       dirty{false};
    std::unordered_map<Key, std::vector<ExpDiskEntry>> table;
    std::vector<TrajectoryStep>                        trajectory;
    std::atomic<int>                                   adaptiveBonus[COLOR_NB]{{0}, {0}};
    std::atomic<i64>                                   timeBankMs{800};
    u64                                                corruptedSkipped{0};
    LearnedSearchGenome                                activeGenome{CompiledLearnedGenome};
};

extern LearnManager GlobalLearn;

}  // namespace Stockfish

#endif  // LEARN_H_INCLUDED
