#!/usr/bin/env python3
"""
STOCKFISH 19 PRO — 5H30M OMNISCIENT EXPERIENCE & META-LEARNING DOJO
====================================================================
Hệ thống rèn luyện đa tầng (4-Layer Omniscient Learning System) chạy 5h30p:
  1. Tầng 1 (Position & Kill-Chain Experience): Học nước đi, điểm TD(λ), độ sâu & tỷ lệ thắng (SF19EXP2).
  2. Tầng 2 (Meta-Learning "Học Cách Học" & Tiến Hóa Bộ Gen Tư Duy):
     - Dùng thuật toán Contextual Evolutionary Bandit (CEM/Thompson) điều chỉnh trực tiếp CÁCH HỌC
       (tdLambdaDecay, winRewardBoost, lossPenaltyMagnitude, drawStagnationPenalty, pvHarvestMaxHorizon)
       và CÁCH TƯ DUY (killerBookEvalMargin, inTreeTtInjectMinPerf, overdriveHeavyMaterialMul, Contempt)
       qua biến môi trường STOCKFISH_GENOME_FILE ở từng ván đấu, giữ lại bộ tham số thắng áp đảo nhất.
  3. Tầng 3 (Giải Phẫu Hậu Chiến & Đúc Kết Mẫu Hình Chiến Thuật - Motif Mining):
     - Phân tích sâu (Post-Mortem Depth 18-20) mọi bước ngoặt (|Δeval| >= 40cp), phân loại mẫu hình
       chiến thuật (Phá bẫy khai cuộc, Công thành hy sinh, Phản công trung tâm, Chuyển hóa tàn cuộc).
  4. Tầng 4 (Tổng Hợp Sổ Tay Tri Thức & Tự Động Đóng Gói Hoàn Chỉnh):
     - Xuất Sổ tay Toàn thư `OMNISCIENT_EXPERIENCE_CODEX.json`, `TRAINING_REPORT.md`, `all_forged_games.pgn`.
     - Tự động tiêm ngược `EmbeddedExperienceBlob` + `learned_genome.h` vào mã nguồn C++ của
       `Stockfish-19-Pro-Ultimate-V3` và đóng gói thành `Stockfish-19-Pro-Ultimate-V3.tar.gz` hoàn chỉnh!
"""

import argparse
import base64
import copy
import gzip
import hashlib
import json
import math
import os
import random
import re
import shutil
import signal
import struct
import subprocess
import sys
import tarfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Dict, List, Optional, Tuple

MAGIC_V2 = b"SF19EXP2"
ENTRY_STRUCT = struct.Struct("<QHhhBBII")  # 24 bytes

# 60 Diverse Grandmaster Openings, Gambits & Sharp Tactical Battlegrounds
OPENING_SUITE: List[Tuple[str, str]] = [
    ("Sicilian Defense: Najdorf Poisoned Pawn", "e2e4 c7c5 g1f3 d7d6 d2d4 c5d4 f3d4 g8f6 b1c3 a7a6 c1g5 e7e6 f2f4 d8b6"),
    ("Sicilian Defense: Najdorf English Attack", "e2e4 c7c5 g1f3 d7d6 d2d4 c5d4 f3d4 g8f6 b1c3 a7a6 f1e3 e7e5 d4b3"),
    ("Sicilian Defense: Dragon Yugoslav Attack", "e2e4 c7c5 g1f3 d7d6 d2d4 c5d4 f3d4 g8f6 b1c3 g7g6 c1e3 f8g7 f2f3 b8c6 d1d2"),
    ("Sicilian Defense: Sveshnikov Sharp", "e2e4 c7c5 g1f3 b8c6 d2d4 c5d4 f3d4 g8f6 b1c3 e7e5 d4b5 d7d6 c1g5 a7a6 b5a3 b7b5"),
    ("Sicilian Defense: Classical Richter-Rauzer", "e2e4 c7c5 g1f3 d7d6 d2d4 c5d4 f3d4 g8f6 b1c3 b8c6 c1g5 e7e6 d1d2"),
    ("Sicilian Defense: Kan/Taimanov Complex", "e2e4 c7c5 g1f3 e7e6 d2d4 c5d4 f3d4 a7a6 b1c3 d8c7 f1d3 g8f6"),
    ("Sicilian Defense: Accelerated Dragon Maroczy", "e2e4 c7c5 g1f3 b8c6 d2d4 c5d4 f3d4 g7g6 c2c4 g8f6 b1c3"),
    ("Sicilian Defense: Smith-Morra Gambit", "e2e4 c7c5 d2d4 c5d4 c2c3 d4c3 b1c3 b8c6 g1f3 d7d6 f1c4"),
    ("Ruy Lopez: Marshall Attack Gambit", "e2e4 e7e5 g1f3 b8c6 f1b5 a7a6 b5a4 g8f6 e1g1 f8e7 f1e1 b7b5 a4b3 e8g8 c2c3 d7d5"),
    ("Ruy Lopez: Closed Breyer System", "e2e4 e7e5 g1f3 b8c6 f1b5 a7a6 b5a4 g8f6 e1g1 f8e7 f1e1 b7b5 a4b3 d7d6 c2c3 e8g8 h2h3 c6b8"),
    ("Ruy Lopez: Open Tactical", "e2e4 e7e5 g1f3 b8c6 f1b5 a7a6 b5a4 g8f6 e1g1 f3e4 d2d4 b7b5 a4b3 d7d5"),
    ("Ruy Lopez: Berlin Endgame Wall", "e2e4 e7e5 g1f3 b8c6 f1b5 g8f6 e1g1 f6e4 d2d4 f8e7 d1e2 e4d6 b5c6 b7c6 d4e5 d6b7"),
    ("Italian Game: Evans Gambit Firestorm", "e2e4 e7e5 g1f3 b8c6 f1c4 f8c5 b2b4 c5b4 c2c3 b4a5 d2d4"),
    ("Italian Game: Giuoco Piano Mainline", "e2e4 e7e5 g1f3 b8c6 f1c4 f8c5 c2c3 g8f6 d2d3 d7d6 e1g1 a7a5"),
    ("Two Knights Defense: Fried Liver / Ulvestad", "e2e4 e7e5 g1f3 b8c6 f1c4 g8f6 f3g5 d7d5 e4d5 c6a5 c4b5 c7c6"),
    ("King's Gambit Accepted: Muzio / Kieseritzky", "e2e4 e7e5 f2f4 e5f4 g1f3 g7g5 h2h4 g5g4 f3e5 g8f6"),
    ("French Defense: Winawer Poisoned Pawn", "e2e4 e7e6 d2d4 d7d5 b1c3 f8b4 e4e5 c7c5 a2a3 b4c3 b2c3 g8e7 d1g4"),
    ("French Defense: Tarrasch Open", "e2e4 e7e6 d2d4 d7d5 b1d2 c7c5 e4d5 e6d5 g1f3 b8c6"),
    ("French Defense: Classical Steinitz", "e2e4 e7e6 d2d4 d7d5 b1c3 g8f6 c1g5 f8e7 e4e5 f6d7 h2h4"),
    ("Caro-Kann Defense: Advance Tal Attack", "e2e4 c7c6 d2d4 d7d5 e4e5 c8f5 h2h4 h7h5 c2c4 e7e6 b1c3"),
    ("Caro-Kann Defense: Panov-Botvinnik Attack", "e2e4 c7c6 d2d4 d7d5 e4d5 c6d5 c2c4 g8f6 b1c3 b8c6 c1g5"),
    ("Pirc Defense: Austrian Attack", "e2e4 d7d6 d2d4 g8f6 b1c3 g7g6 f2f4 f8g7 g1f3 c7c5 d4c5 d8a5"),
    ("Alekhine Defense: Four Pawns Attack", "e2e4 g8f6 e4e5 f6d5 d2d4 d7d6 c2c4 d5b6 f2f4 d6e5 f4e5"),
    ("Scandinavian Defense: Modern Portugese Gambit", "e2e4 d7d5 e4d5 g8f6 d2d4 c8g4 f2f3 g4f5 c2c4 e7e6"),
    ("Queen's Gambit Declined: Ragozin / Vienna", "d2d4 d7d5 c2c4 e7e6 b1c3 g8f6 g1f3 f8b4 c4d5 e6d5 c1g5"),
    ("Queen's Gambit Declined: Semi-Slav Botvinnik", "d2d4 d7d5 c2c4 c7c6 g1f3 g8f6 b1c3 e7e6 c1g5 d5c4 e2e4 b7b5 e4e5 h7h6 g5h4 g7g5"),
    ("Queen's Gambit Declined: Semi-Slav Meran", "d2d4 d7d5 c2c4 c7c6 g1f3 g8f6 b1c3 e7e6 e2e3 b8d7 f1d3 d5c4 d3c4 b7b5"),
    ("Slav Defense: Mainline Chebanenko", "d2d4 d7d5 c2c4 c7c6 g1f3 g8f6 b1c3 a7a6 e2e3 b7b5"),
    ("Queen's Gambit Accepted: Central Breakthrough", "d2d4 d7d5 c2c4 d5c4 g1f3 g8f6 e2e4 e7e5 f1c4 f8b4"),
    ("King's Indian Defense: Mar del Plata Attack", "d2d4 g8f6 c2c4 g7g6 b1c3 f8g7 e2e4 d7d6 g1f3 e8g8 f1e2 e7e5 e1g1 b8c6 d4d5 c6e7"),
    ("King's Indian Defense: Samisch Pawn Storm", "d2d4 g8f6 c2c4 g7g6 b1c3 f8g7 e2e4 d7d6 f2f3 e8g8 c1e3 e7e5 d4d5 c7c6"),
    ("King's Indian Defense: Four Pawns Attack", "d2d4 g8f6 c2c4 g7g6 b1c3 f8g7 e2e4 d7d6 f2f4 e8g8 g1f3 c7c5 d4d5"),
    ("Grunfeld Defense: Exchange Classical", "d2d4 g8f6 c2c4 g7g6 b1c3 d7d5 c4d5 f6d5 e2e4 d5c3 b2c3 f8g7 f1c4 c7c5 g1e2"),
    ("Grunfeld Defense: Russian System", "d2d4 g8f6 c2c4 g7g6 b1c3 d7d5 g1f3 f8g7 d1b3 d5c4 b3c4 e8g8 e2e4"),
    ("Nimzo-Indian Defense: Rubinstein / Kasparov", "d2d4 g8f6 c2c4 e7e6 b1c3 f8b4 e2e3 e8g8 f1d3 d7d5 g1f3 c7c5"),
    ("Nimzo-Indian Defense: Samisch Sharp", "d2d4 g8f6 c2c4 e7e6 b1c3 f8b4 a2a3 b4c3 b2c3 c7c5 f2f3 d7d5"),
    ("Queen's Indian Defense: Petrosian System", "d2d4 g8f6 c2c4 e7e6 g1f3 b7b6 a2a3 c8b7 b1c3 d7d5"),
    ("Bogo-Indian / Catalan Open Mainline", "d2d4 g8f6 c2c4 e7e6 g2g3 d7d5 f1g2 d5c4 g1f3 a7a6 e1g1 b7b5"),
    ("Catalan Opening: Closed Fortress", "d2d4 g8f6 c2c4 e7e6 g2g3 d7d5 f1g2 f8e7 g1f3 e8g8 e1g1 d5c4 d1c2"),
    ("Benoni Defense: Modern Tactical", "d2d4 g8f6 c2c4 c7c5 d4d5 e7e6 b1c3 e6d5 c4d5 d7d6 e2e4 g7g6 f2f4"),
    ("Benko Gambit Accepted: Full Compensation", "d2d4 g8f6 c2c4 c7c5 d4d5 b7b5 c4b5 a7a6 b5a6 c8a6 b1c3 d7d6 e2e4"),
    ("Dutch Defense: Leningrad Dynamic", "d2d4 f7f5 g2g3 g8f6 f1g2 g7g6 g1f3 f8g7 e1g1 e8g8 c2c4 d7d6 b1c3"),
    ("Budapest Gambit: Adler / Fajarowicz", "d2d4 g8f6 c2c4 e7e5 d4e5 f6g4 g1f3 f8c5 e2e3 b8c6"),
    ("Albin Countergambit: Tactical Minefield", "d2d4 d7d5 c2c4 e7e5 d4e5 d5d4 g1f3 b8c6 g2g3 c8e6"),
    ("English Opening: Symmetrical Hedgehog", "c2c4 c7c5 g1f3 g8f6 b1c3 e7e6 g2g3 b7b6 f1g2 c8b7 e1g1 f8e7"),
    ("English Opening: Reversed Sicilian", "c2c4 e7e5 b1c3 g8f6 g1f3 b8c6 g2g3 d7d5 c4d5 f6d5 f1g2"),
    ("Reti / King's Indian Attack Complex", "g1f3 d7d5 g2g3 g8f6 f1g2 c7c6 e1g1 c8f5 d2d3 e7e6 b1d2"),
    ("Bird's Opening: From's Gambit", "f2f4 e7e5 f4e5 d7d6 e5d6 f8d6 g1f3 g7g5 d2d4 g5g4"),
    ("London System: Poisoned Jobava Attack", "d2d4 g8f6 b1c3 d7d5 c1f4 c7c5 e2e3 b8c6 c3b5"),
    ("Trompowsky Attack: Sharp Poison", "d2d4 g8f6 c1g5 f6e4 g5f4 c7c5 f2f3 d8a5 c2c3 e4f6"),
    ("Scotch Game: Mieses Extreme", "e2e4 e7e5 g1f3 b8c6 d2d4 e5d4 f3d4 g8f6 d4c6 b7c6 e4e5 d8e7 d1e2 f6d5"),
    ("Four Knights Game: Halloween / Belgrade", "e2e4 e7e5 g1f3 b8c6 b1c3 g8f6 d2d4 e5d4 c3d5"),
    ("Vienna Game: Frankenstein-Dracula Variation", "e2e4 e7e5 b1c3 g8f6 f1c4 f6e4 d1h5 e4d6 c4b3 b8c6"),
    ("Petrov's Defense: Cochrane Gambit", "e2e4 e7e5 g1f3 g8f6 f3e5 d7d6 e5f7 e8f7 d2d4 c7c5"),
    ("Philidor Defense: Hanham Counterattack", "e2e4 e7e5 g1f3 d7d6 d2d4 e5d4 f3d4 g8f6 b1c3 f8e7"),
    ("Modern Defense: Monkey's Bum / Averbakh", "e2e4 g7g6 d2d4 f8g7 b1c3 d7d6 f2f4 c7c6 g1f3 d8b6"),
    ("Nimzowitsch-Larsen Attack: Hypermodern", "b2b3 e7e5 c1b2 b8c6 e2e3 g8f6 f1b5 f8d6 g1e2"),
    ("Queen's Pawn: Blackmar-Diemer Gambit", "d2d4 d7d5 e2e4 d5e4 b1c3 g8f6 f2f3 e4f3 g1f3"),
    ("Endgame Crucible: Rook + Minor Imbalance", "e2e4 e7e5 g1f3 b8c6 f1b5 a7a6 b5c6 d7c6 d2d4 e5d4 d1d4 d8d4 f3d4 c8d7"),
    ("Tactical Crucible: Opposite-Side Castling Storm", "e2e4 c7c5 g1f3 d7d6 d2d4 c5d4 f3d4 g8f6 b1c3 b8c6 c1g5 e7e6 d1d2 a7a6 e1c1 c8d7 f2f4"),
]

# Parameter Bounds & Baseline for Contextual Meta-Learning (Learning HOW to Learn & Search)
GENOME_SPEC: Dict[str, Tuple[int, int, int, str]] = {
    # Layer 1: Meta-Learning Rules ("Cách học & truyền ngược kinh nghiệm")
    "tdLambdaDecayPermille":     (945, 890, 985, "Hệ số truyền ngược TD-Lambda qua từng nước cờ (permille)"),
    "tdBlendTrajectoryWeight":   (58,  35,  80,  "Tỷ trọng kết quả cuối ván so với đánh giá cục bộ (%)"),
    "winRewardBoost":            (335, 250, 440, "Biên độ thưởng khắc sâu chuỗi nước chiến thắng"),
    "lossPenaltyMagnitude":      (340, 250, 450, "Biên độ phạt triệt tiêu nhánh dẫn tới thất bại"),
    "drawStagnationPenalty":     (22,  10,  45,  "Mức phạt chống lặp lại các biến hòa vô bổ để tự mở lối đi mới"),
    "pvHarvestMaxHorizon":       (4,   2,   6,   "Số ply nhánh biến chính (PV) thu hoạch tự động trong lúc suy nghĩ"),

    # Layer 2: Experience Exploitation Policy ("Cách vận dụng kinh nghiệm trong cây tìm kiếm")
    "killerBookEvalMargin":      (58,  38,  85,  "Biên độ bảo vệ nước đi Sát Thủ trong kho kinh nghiệm (Internal Value)"),
    "standardBookEvalMargin":    (30,  16,  48,  "Biên độ bảo vệ nước đi kinh nghiệm tiêu chuẩn"),
    "rootHistoryKillerBoost":    (980, 700, 1280,"Xung lực lịch sử ưu tiên nhánh Killer tại gốc"),
    "lookaheadHorizonBoost1":    (480, 300, 720, "Xung lực lịch sử nhìn trước 1 ply từ kho kinh nghiệm"),
    "lookaheadHorizonBoost2":    (460, 280, 680, "Xung lực lịch sử nhìn trước 2 ply từ kho kinh nghiệm"),
    "refutedMoveHistoryPenalty": (-980,-1350,-650,"Mức phạt lịch sử khóa chặt các nước đi đã từng bị phản bác"),
    "inTreeTtInjectMinPerf":     (175, 145, 192, "Ngưỡng hiệu suất tối thiểu để tiêm thẳng nước cờ vào bảng băm TT"),

    # Layer 3: Phase-Adaptive Search Cortex ("Tư duy chiến thuật & phân bổ công suất")
    "openingOptimismSkew":       (4,   1,   10,  "Độ sắc bén công kích giai đoạn Khai cuộc"),
    "middlegameOptimismSkew":    (8,   3,   16,  "Độ sắc bén công kích giai đoạn Trung cuộc phức tạp"),
    "endgameOptimismSkew":       (5,   1,   12,  "Độ chính xác chuyển hóa ưu thế giai đoạn Tàn cuộc"),
    "winningContemptPress":      (18,  10,  32,  "Áp lực từ chối hòa khi đang nắm ưu thế"),
    "defendingContemptBailout":  (-15, -28, -6,  "Chủ động tìm biến đỡ hòa khi thế trận bất lợi"),
    "overdriveHeavyMaterialMul": (3500,2600,4200,"Hệ số đốt công suất tính toán ở trung cuộc nhiều quân (permille)"),
    "overdriveTacticalSwingMul": (2550,1800,3400,"Hệ số đốt công suất khi thế trận biến động chiến thuật (permille)"),

    # Layer 4: Empirical Motif & Momentum Heuristics ("Nhận diện mẫu hình & xung lực thế trận")
    "complexTensionBonus":       (6,   2,   14,  "Thưởng giữ sức căng đa quân trên bàn cờ"),
    "initiativeMomentumStep":    (3,   1,   6,   "Bước nhảy xung lực khi liên tục gia tăng ưu thế"),
    "maxAdaptiveMomentum":       (10,  6,   16,  "Biên độ xung lực thích ứng tối đa trong ván đấu"),
}


class MetaGenomeLearner:
    """
    Contextual Evolutionary Bandit (Cross-Entropy Method / Thompson Sampling)
    that continuously learns BOTH how Stockfish Pro learns experience AND how it searches.
    """

    def __init__(self) -> None:
        self.mean: Dict[str, float] = {k: float(v[0]) for k, v in GENOME_SPEC.items()}
        self.std: Dict[str, float] = {
            k: max(1.0, (v[2] - v[1]) * 0.14) for k, v in GENOME_SPEC.items()
        }
        self.best_genome: Dict[str, int] = {k: int(v[0]) for k, v in GENOME_SPEC.items()}
        self.best_fitness: float = 0.0
        self.generations: List[Dict] = []
        self.samples_history: List[Tuple[Dict[str, int], float]] = []

    def sample_candidate(self, explore_rate: float = 0.75) -> Dict[str, int]:
        if random.random() > explore_rate:
            return dict(self.best_genome)
        cand: Dict[str, int] = {}
        for k, (default_val, lo, hi, _) in GENOME_SPEC.items():
            val = int(round(random.gauss(self.mean[k], self.std[k])))
            cand[k] = max(lo, min(hi, val))
        return cand

    def record_episode(
        self,
        candidate: Dict[str, int],
        pro_score: float,        # 1.0 win, 0.5 draw, 0.0 loss
        plies: int,
        new_exp_entries: int,
        surgeries_solved: int,
        blunders_committed: int,
    ) -> float:
        # Composite meta-learning reward:
        # Rewards decisive wins, fast kills, high experience yield, and zero blunders!
        speed_bonus = max(0.0, (140 - min(plies, 140)) / 280.0) if pro_score > 0.75 else 0.0
        harvest_bonus = min(0.35, new_exp_entries / 250.0) + min(0.25, surgeries_solved * 0.05)
        blunder_pen = min(0.45, blunders_committed * 0.12)
        fitness = (pro_score * 1.5) + speed_bonus + harvest_bonus - blunder_pen

        self.samples_history.append((candidate, fitness))
        if fitness > self.best_fitness:
            self.best_fitness = fitness
            self.best_genome = dict(candidate)

        # Every 4 episodes (or whenever enough samples accumulate), update mean/std toward top 35% elites
        if len(self.samples_history) >= 4:
            recent = self.samples_history[-16:]
            recent_sorted = sorted(recent, key=lambda x: x[1], reverse=True)
            elite_count = max(2, len(recent_sorted) // 3)
            elites = recent_sorted[:elite_count]
            for k, (_, lo, hi, _) in GENOME_SPEC.items():
                elite_vals = [e[0][k] for e in elites]
                elite_mean = sum(elite_vals) / len(elite_vals)
                self.mean[k] = float(max(lo, min(hi, 0.65 * self.mean[k] + 0.35 * elite_mean)))
                if len(elite_vals) > 1:
                    var = sum((x - elite_mean) ** 2 for x in elite_vals) / len(elite_vals)
                    new_std = math.sqrt(var)
                    min_std = max(1.0, (hi - lo) * 0.04)
                    max_std = max(2.0, (hi - lo) * 0.22)
                    self.std[k] = max(min_std, min(max_std, 0.75 * self.std[k] + 0.25 * new_std))
            self.best_genome = {k: int(round(self.mean[k])) for k in GENOME_SPEC}
            self.generations.append(
                {
                    "episodes": len(self.samples_history),
                    "avg_elite_fitness": round(sum(e[1] for e in elites) / len(elites), 4),
                    "evolved_genome": dict(self.best_genome),
                }
            )
        return fitness

    def write_genome_ini(self, genome: Dict[str, int], path: Path) -> None:
        lines = [f"{k}={v}" for k, v in genome.items()]
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def render_cpp_header(self) -> str:
        g = self.best_genome
        lines = [
            "/*",
            "  Stockfish 19-Pro Ultimate V7.5 — Omniscient Meta-Learning & Search Genome",
            "  Auto-forged and continuously evolved by the 5h30m Multi-Board Experience Dojo.",
            "*/",
            "",
            "#ifndef LEARNED_GENOME_H_INCLUDED",
            "#define LEARNED_GENOME_H_INCLUDED",
            "",
            "namespace Stockfish {",
            "",
            "struct LearnedSearchGenome {",
        ]
        for k, (_, _, _, desc) in GENOME_SPEC.items():
            val = g.get(k, GENOME_SPEC[k][0])
            lines.append(f"    int {k:<28} = {val:<6}; // {desc}")
        lines += [
            "};",
            "",
            "inline constexpr LearnedSearchGenome CompiledLearnedGenome{};",
            "",
            "}  // namespace Stockfish",
            "",
            "#endif  // LEARNED_GENOME_H_INCLUDED",
            "",
        ]
        return "\n".join(lines)


def fnv1a_checksum(pos_key: int, move_raw: int, score: int, td_score: int, depth: int, win_perf: int, games_count: int) -> int:
    raw20 = struct.pack("<QHhhBBI", pos_key, move_raw, score, td_score, depth, win_perf, games_count)
    h = 2166136261
    for b in raw20:
        h ^= b
        h = (h * 16777619) & 0xFFFFFFFF
    return h if h != 0 else 1


def load_experience_bin(path: Path) -> Dict[Tuple[int, int], Tuple[int, int, int, int, int]]:
    entries: Dict[Tuple[int, int], Tuple[int, int, int, int, int]] = {}
    if not path.exists():
        return entries
    data = path.read_bytes()
    if len(data) < 16 or data[:8] not in (b"SF19EXP2", b"SF19EXP1"):
        return entries
    offset = 16
    while offset + 24 <= len(data):
        pos_key, move_raw, score, td_score, depth, win_perf, games_count, _ = ENTRY_STRUCT.unpack_from(data, offset)
        offset += 24
        if pos_key == 0 or move_raw == 0:
            continue
        key = (pos_key, move_raw)
        if key not in entries or depth > entries[key][2] or (depth == entries[key][2] and win_perf > entries[key][3]):
            entries[key] = (score, td_score, depth, win_perf, max(1, games_count))
    return entries


def save_experience_bin(entries: Dict[Tuple[int, int], Tuple[int, int, int, int, int]], path: Path) -> bytes:
    sorted_items = sorted(entries.items(), key=lambda kv: (kv[0][0], -kv[1][3], -kv[1][2]))
    if len(sorted_items) > 250000:
        sorted_items = sorted_items[:250000]
    buf = bytearray(16 + 24 * len(sorted_items))
    buf[:8] = MAGIC_V2
    struct.pack_into("<Q", buf, 8, len(sorted_items))
    offset = 16
    for (pos_key, move_raw), (score, td_score, depth, win_perf, games_count) in sorted_items:
        score = max(-30000, min(30000, int(score)))
        td_score = max(-30000, min(30000, int(td_score)))
        depth = max(1, min(245, int(depth)))
        win_perf = max(0, min(200, int(win_perf)))
        games_count = max(1, min(10000000, int(games_count)))
        csum = fnv1a_checksum(pos_key, move_raw, score, td_score, depth, win_perf, games_count)
        ENTRY_STRUCT.pack_into(buf, offset, pos_key, move_raw, score, td_score, depth, win_perf, games_count, csum)
        offset += 24
    raw_bytes = bytes(buf)
    path.write_bytes(raw_bytes)
    return raw_bytes


def merge_experience_dicts(
    master: Dict[Tuple[int, int], Tuple[int, int, int, int, int]],
    worker: Dict[Tuple[int, int], Tuple[int, int, int, int, int]],
) -> int:
    added_or_upgraded = 0
    for key, (w_score, w_td, w_depth, w_perf, w_games) in worker.items():
        if key not in master:
            master[key] = (w_score, w_td, w_depth, w_perf, w_games)
            added_or_upgraded += 1
        else:
            m_score, m_td, m_depth, m_perf, m_games = master[key]
            if m_perf >= 180 and m_depth >= 24 and w_td > -220:
                master[key] = (m_score, m_td, m_depth, m_perf, max(m_games, w_games))
                continue
            new_depth = max(m_depth, w_depth)
            new_score = w_score if w_depth >= m_depth else m_score
            new_td = int((m_td * 3 + w_td * 2) / 5)
            new_perf = int((m_perf * 2 + w_perf * 3) / 5)
            new_games = m_games + max(1, w_games - m_games)
            if new_depth > m_depth or abs(new_td - m_td) >= 8:
                added_or_upgraded += 1
            master[key] = (new_score, new_td, new_depth, new_perf, new_games)
    return added_or_upgraded


def classify_tactical_motif(ply: int, swing_cp: int, best_move: str, refutation_score_cp: int) -> str:
    if ply <= 24:
        return "Opening_Trap_Refutation (Phá bẫy & trừng phạt sai lầm khai cuộc)"
    if abs(refutation_score_cp) >= 450:
        return "Decisive_Kill_Combination (Đòn phối hợp sát cục / ăn hơn chất quyết định)"
    if ply <= 65 and swing_cp >= 90:
        return "Middlegame_King_Storm_Breakthrough (Đột phá công thành & xé toạc trung tâm)"
    if ply <= 75:
        return "Central_Tension_Counterstrike (Phản kích giành quyền chủ động trung cuộc)"
    return "Endgame_Precision_Conversion (Chuyển hóa ưu thế & phá pháo đài tàn cuộc)"


class UCISession:
    def __init__(self, binary_path: Path, options: Dict[str, str], env_overrides: Optional[Dict[str, str]] = None) -> None:
        env = os.environ.copy()
        if env_overrides:
            env.update(env_overrides)
        self.proc = subprocess.Popen(
            [str(binary_path)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            bufsize=1,
            env=env,
        )
        self._send("uci")
        self._wait_for("uciok")
        for k, v in options.items():
            self._send(f"setoption name {k} value {v}")
        self._send("isready")
        self._wait_for("readyok")

    def _send(self, cmd: str) -> None:
        if self.proc.stdin:
            self.proc.stdin.write(cmd + "\n")
            self.proc.stdin.flush()

    def _wait_for(self, token: str, timeout: float = 30.0) -> List[str]:
        lines: List[str] = []
        deadline = time.time() + timeout
        while time.time() < deadline:
            if not self.proc.stdout:
                break
            line = self.proc.stdout.readline()
            if not line:
                break
            s = line.strip()
            lines.append(s)
            if s.startswith(token):
                break
        return lines

    def search_move(self, moves: List[str], movetime_ms: int = 100, depth: Optional[int] = None) -> Tuple[str, int, int, List[str]]:
        pos_cmd = "position startpos"
        if moves:
            pos_cmd += " moves " + " ".join(moves)
        self._send(pos_cmd)
        if depth is not None:
            self._send(f"go depth {depth}")
            lines = self._wait_for("bestmove", timeout=60.0)
        else:
            self._send(f"go movetime {movetime_ms}")
            lines = self._wait_for("bestmove", timeout=max(15.0, movetime_ms / 100.0 + 10.0))

        bestmove = "0000"
        score_cp = 0
        reached_depth = 1
        pv: List[str] = []
        for ln in lines:
            if ln.startswith("info ") and " score " in ln and " pv " in ln and "lowerbound" not in ln and "upperbound" not in ln:
                m_d = re.search(r"\bdepth\s+(\d+)", ln)
                if m_d:
                    reached_depth = int(m_d.group(1))
                m_cp = re.search(r"\bscore\s+cp\s+(-?\d+)", ln)
                m_mate = re.search(r"\bscore\s+mate\s+(-?\d+)", ln)
                if m_cp:
                    score_cp = int(m_cp.group(1))
                elif m_mate:
                    mv = int(m_mate.group(1))
                    score_cp = 10000 - abs(mv) * 20 if mv > 0 else -10000 + abs(mv) * 20
                idx = ln.find(" pv ")
                if idx != -1:
                    pv = ln[idx + 4 :].strip().split()
            elif ln.startswith("bestmove "):
                parts = ln.split()
                if len(parts) >= 2:
                    bestmove = parts[1]
        return bestmove, score_cp, reached_depth, pv

    def inject_line(self, color_char: str, depth: int, win_perf: int, score_val: int, games_cnt: int, moves: List[str], start_ply: int = 0) -> None:
        if not moves:
            return
        cmd = f"expinject {color_char} {depth} {win_perf} {score_val} {games_cnt} {start_ply} {len(moves)} " + " ".join(moves)
        self._send(cmd)
        self._send("isready")
        self._wait_for("readyok")

    def close(self) -> None:
        try:
            self._send("quit")
            self.proc.wait(timeout=3.0)
        except Exception:
            self.proc.kill()


def play_and_learn_game(
    worker_id: int,
    game_idx: int,
    pro_bin: Path,
    sparring_bin: Path,
    worker_exp_path: Path,
    worker_genome_path: Path,
    threads_per_engine: int,
    move_time_ms: int,
    post_mortem_depth: int,
    mode: str,
) -> Dict:
    opening_name, opening_uci = OPENING_SUITE[(game_idx - 1) % len(OPENING_SUITE)]
    moves: List[str] = opening_uci.split()

    if mode == "hybrid_all":
        game_type = "CRUCIBLE_VS_BASELINE" if (game_idx % 3 != 0) else "PERSONA_SELFPLAY"
    elif mode == "selfplay_persona":
        game_type = "PERSONA_SELFPLAY"
    else:
        game_type = "CRUCIBLE_VS_BASELINE"

    pro_is_white = (game_idx % 2 == 1)
    env_pro = {"STOCKFISH_GENOME_FILE": str(worker_genome_path)}

    pro_opts = {
        "Threads": str(threads_per_engine),
        "Hash": "64",
        "Experience Enabled": "true",
        "Experience Book": "true",
        "Experience File": str(worker_exp_path),
        "Experience Learning Rate": "100",
        "Deep Search Scaler": "true",
        "Dynamic Contempt": "36",
    }

    if game_type == "CRUCIBLE_VS_BASELINE":
        opp_bin = sparring_bin
        opp_opts = {
            "Threads": str(threads_per_engine),
            "Hash": "64",
        }
        env_opp = None
    else:
        opp_bin = pro_bin
        opp_opts = {
            "Threads": str(threads_per_engine),
            "Hash": "64",
            "Experience Enabled": "true",
            "Experience Book": "true",
            "Experience File": str(worker_exp_path),
            "Experience Learning Rate": "100",
            "Deep Search Scaler": "true",
            "Dynamic Contempt": "14" if pro_is_white else "58",
        }
        env_opp = env_pro

    white_engine = UCISession(pro_bin if pro_is_white else opp_bin, pro_opts if pro_is_white else opp_opts, env_pro if pro_is_white else env_opp)
    black_engine = UCISession(opp_bin if pro_is_white else pro_bin, opp_opts if pro_is_white else pro_opts, env_opp if pro_is_white else env_pro)

    history_steps: List[Tuple[int, str, str, int, int, List[str]]] = []
    adjudicated_result: Optional[str] = None
    win_streak = 0
    draw_streak = 0

    try:
        for ply in range(len(moves), 170):
            side = "W" if (ply % 2 == 0) else "B"
            eng = white_engine if side == "W" else black_engine
            bm, cp, d, pv = eng.search_move(moves, movetime_ms=move_time_ms)
            if bm == "0000" or not bm:
                adjudicated_result = "0-1" if side == "W" else "1-0"
                break

            white_cp = cp if side == "W" else -cp
            history_steps.append((ply, side, bm, cp, d, pv))
            moves.append(bm)

            if abs(white_cp) >= 650:
                win_streak += 1
                if win_streak >= 5:
                    adjudicated_result = "1-0" if white_cp > 0 else "0-1"
                    break
            else:
                win_streak = 0

            if ply >= 64 and abs(white_cp) <= 12:
                draw_streak += 1
                if draw_streak >= 12:
                    adjudicated_result = "1/2-1/2"
                    break
            else:
                draw_streak = 0
    finally:
        white_engine.close()
        black_engine.close()

    if adjudicated_result is None:
        if history_steps:
            last_ply, last_side, _, last_cp, _, _ = history_steps[-1]
            final_white_cp = last_cp if last_side == "W" else -last_cp
            if final_white_cp >= 220:
                adjudicated_result = "1-0"
            elif final_white_cp <= -220:
                adjudicated_result = "0-1"
            else:
                adjudicated_result = "1/2-1/2"
        else:
            adjudicated_result = "1/2-1/2"

    # Identify Critical Turning Points (|Δeval| >= 40 cp) & Blunders for Deep Post-Mortem Surgery
    turning_points: List[Tuple[int, List[str], str, int]] = []
    pro_blunders = 0
    prev_white_cp: Optional[int] = None
    reconstructed: List[str] = opening_uci.split()

    for ply, side, bm, cp, d, _ in history_steps:
        white_cp = cp if side == "W" else -cp
        if prev_white_cp is not None and ply <= 115:
            delta_white = white_cp - prev_white_cp
            mover_lost_cp = -delta_white if side == "W" else delta_white
            is_pro_move = (side == "W" and pro_is_white) or (side == "B" and not pro_is_white)
            if mover_lost_cp >= 42:
                turning_points.append((ply, list(reconstructed), side, mover_lost_cp))
                if is_pro_move and mover_lost_cp >= 65:
                    pro_blunders += 1
        prev_white_cp = white_cp
        reconstructed.append(bm)

    # Sort turning points by largest mistake and perform Deep Post-Mortem Surgery (up to 4 per game)
    turning_points.sort(key=lambda x: x[3], reverse=True)
    selected_surgeries = turning_points[:4]

    surgeon = UCISession(
        pro_bin,
        {
            "Threads": str(threads_per_engine),
            "Hash": "64",
            "Experience Enabled": "true",
            "Experience Book": "false",
            "Experience File": str(worker_exp_path),
            "Experience Learning Rate": "100",
        },
        env_pro,
    )
    solved_lessons: List[Dict] = []
    try:
        # 1. If a side won decisively, harvest the entire winning trajectory as a verified Kill-Chain!
        if adjudicated_result in ("1-0", "0-1"):
            winner_char = "W" if adjudicated_result == "1-0" else "B"
            surgeon.inject_line(winner_char, 24, 188, 300, 15, moves[:110], start_ply=0)

        # 2. Perform Deep Post-Mortem Surgery on turning points
        for ply, pos_moves, side_char, swing_cp in selected_surgeries:
            bm, ref_cp, ref_d, ref_pv = surgeon.search_move(pos_moves, depth=post_mortem_depth)
            if bm != "0000" and ref_pv:
                inject_seq = pos_moves + ref_pv[:6]
                val_internal = max(-4000, min(4000, int(ref_cp * 2.08)))
                perf = 192 if ref_cp >= 80 else (175 if ref_cp >= -15 else 145)
                surgeon.inject_line(side_char, max(20, ref_d), perf, val_internal, 20, inject_seq, start_ply=ply)
                motif_label = classify_tactical_motif(ply, swing_cp, bm, ref_cp)
                solved_lessons.append(
                    {
                        "game": game_idx,
                        "opening": opening_name,
                        "ply": ply,
                        "side": side_char,
                        "blunder_swing_cp": swing_cp,
                        "surgical_bestmove": bm,
                        "surgical_score_cp": ref_cp,
                        "surgical_depth": ref_d,
                        "surgical_pv": " ".join(ref_pv[:6]),
                        "motif": motif_label,
                    }
                )
    finally:
        surgeon.close()

    if adjudicated_result == "1-0":
        pro_score = 1.0 if pro_is_white else 0.0
    elif adjudicated_result == "0-1":
        pro_score = 0.0 if pro_is_white else 1.0
    else:
        pro_score = 0.5

    return {
        "worker_id": worker_id,
        "game_idx": game_idx,
        "game_type": game_type,
        "opening": opening_name,
        "pro_color": "White" if pro_is_white else "Black",
        "result": adjudicated_result,
        "pro_score": pro_score,
        "plies": len(moves),
        "moves_uci": " ".join(moves),
        "pro_blunders": pro_blunders,
        "surgeries_count": len(solved_lessons),
        "solved_lessons": solved_lessons,
    }


def export_all_artifacts(
    output_dir: Path,
    master_entries: Dict[Tuple[int, int], Tuple[int, int, int, int, int]],
    meta_learner: MetaGenomeLearner,
    stats: Dict,
    critical_lessons: List[Dict],
    pgn_games: List[str],
    opening_stats: Dict[str, Dict[str, int]],
    motif_counts: Dict[str, int],
    engine_source_dir: Optional[Path] = None,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    exp_bin_path = output_dir / "experience.bin"
    exp_bytes = save_experience_bin(master_entries, exp_bin_path)
    count = len(master_entries)
    sha256_hex = hashlib.sha256(exp_bytes).hexdigest()

    # 1. Export embedded_experience_blob.h
    hex_lines = []
    for i in range(0, len(exp_bytes), 24):
        chunk = exp_bytes[i : i + 24]
        hex_lines.append("    " + ", ".join(f"0x{b:02x}" for b in chunk) + ",")
    blob_header = (
        f"// Auto-generated by Stockfish 19 Pro 5h30m Omniscient Dojo\n"
        f"// Entries: {count:,} | Size: {len(exp_bytes):,} bytes | Format: SF19EXP2\n"
        f"alignas(8) static constexpr unsigned char EmbeddedExperienceBlob[{len(exp_bytes)}] = {{\n"
        + "\n".join(hex_lines)
        + "\n};\n"
    )
    (output_dir / "embedded_experience_blob.h").write_text(blob_header, encoding="utf-8")

    # 2. Export learned_genome.h & learned_genome.json
    genome_cpp = meta_learner.render_cpp_header()
    (output_dir / "learned_genome.h").write_text(genome_cpp, encoding="utf-8")
    (output_dir / "learned_genome.json").write_text(
        json.dumps(
            {
                "evolved_genome": meta_learner.best_genome,
                "parameter_descriptions": {k: v[3] for k, v in GENOME_SPEC.items()},
                "generations_history": meta_learner.generations,
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    # 3. Export PGN Database of all forged games
    if pgn_games:
        (output_dir / "all_forged_games.pgn").write_text("\n\n".join(pgn_games) + "\n", encoding="utf-8")

    # 4. Export OMNISCIENT_EXPERIENCE_CODEX.json (Toàn thư tổng hợp mọi kiểu kinh nghiệm)
    codex = {
        "summary": {
            "version": "Stockfish 19 Pro — V7.5 Omniscient Singularity Edition",
            "elapsed_seconds": stats["elapsed_sec"],
            "elapsed_formatted": stats["elapsed_str"],
            "initial_experience_entries": stats["initial_entries"],
            "final_experience_entries": count,
            "net_new_or_upgraded_entries": count - stats["initial_entries"],
            "experience_bin_bytes": len(exp_bytes),
            "experience_bin_sha256": sha256_hex,
            "total_games": stats["games_played"],
            "crucible_games": stats["crucible_games"],
            "crucible_pro_wins": stats["pro_wins"],
            "crucible_draws": stats["draws"],
            "crucible_sparring_wins": stats["sparring_wins"],
            "selfplay_games": stats["selfplay_games"],
            "kill_chains_harvested": stats["kill_chains"],
            "post_mortem_surgeries_solved": stats["surgeries_solved"],
        },
        "layer_1_position_experience": {
            "format": "SF19EXP2 (24-byte Zobrist + Move + Score + TD_Score + Depth + WinPerf + Games + FNV1a)",
            "total_positions_and_moves": count,
            "opening_mastery_ledger": opening_stats,
        },
        "layer_2_meta_learning_how_to_learn": {
            "algorithm": "Contextual Evolutionary Bandit (Cross-Entropy + Thompson Sampling)",
            "evolved_parameters": meta_learner.best_genome,
            "evolution_log": meta_learner.generations[-20:],
        },
        "layer_3_tactical_motifs_and_post_mortem": {
            "motif_distribution": motif_counts,
            "deep_surgical_refutations": critical_lessons[-200:],
        },
    }
    (output_dir / "OMNISCIENT_EXPERIENCE_CODEX.json").write_text(
        json.dumps(codex, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    (output_dir / "critical_positions_solved.json").write_text(
        json.dumps(critical_lessons[-200:], indent=2, ensure_ascii=False), encoding="utf-8"
    )
    (output_dir / "training_summary.json").write_text(
        json.dumps(codex["summary"], indent=2, ensure_ascii=False), encoding="utf-8"
    )

    # 5. Automatically inject BOTH EmbeddedExperienceBlob AND learned_genome.h back into C++ source tree
    # and package Stockfish-19-Pro-Ultimate-V3.tar.gz inside output_dir!
    repackaged_tar_info = "Chưa đóng gói tar.gz (không truyền --engine-src-dir)"
    if engine_source_dir and engine_source_dir.exists():
        try:
            src_sub = engine_source_dir / "src"
            exp_sub = engine_source_dir / "experience"
            exp_sub.mkdir(parents=True, exist_ok=True)
            shutil.copy2(exp_bin_path, exp_sub / "experience.bin")
            shutil.copy2(output_dir / "learned_genome.h", src_sub / "learned_genome.h")

            lc_path = src_sub / "learn.cpp"
            if lc_path.exists():
                lc_txt = lc_path.read_text(encoding="utf-8")
                new_blob_def = (
                    f"alignas(8) static constexpr unsigned char EmbeddedExperienceBlob[{len(exp_bytes)}] = {{\n"
                    + "\n".join(hex_lines)
                    + "\n};"
                )
                lc_txt = re.sub(
                    r"alignas\(8\)\s+static\s+constexpr\s+unsigned\s+char\s+EmbeddedExperienceBlob\[\d+\]\s*=\s*\{[\s\S]*?\};",
                    lambda _: new_blob_def,
                    lc_txt,
                    count=1,
                )
                lc_path.write_text(lc_txt, encoding="utf-8")

            # Also copy the codex into engine_source_dir/experience/
            shutil.copy2(output_dir / "OMNISCIENT_EXPERIENCE_CODEX.json", exp_sub / "OMNISCIENT_EXPERIENCE_CODEX.json")
            shutil.copy2(output_dir / "learned_genome.json", exp_sub / "learned_genome.json")

            tar_out = output_dir / "Stockfish-19-Pro-Ultimate-V3.tar.gz"
            with tarfile.open(tar_out, "w:gz") as tf:
                tf.add(engine_source_dir, arcname="Stockfish-19-Pro-Ultimate-V3")
            repackaged_tar_info = f"`Stockfish-19-Pro-Ultimate-V3.tar.gz` ({tar_out.stat().st_size / (1024*1024):.2f} MB)"
        except Exception as e:
            repackaged_tar_info = f"Lỗi đóng gói tự động: {e}"

    # 6. Export termux_inject_forged_experience.sh (1-command Termux builder with BOTH experience.bin AND learned_genome.h embedded!)
    exp_gz_b64 = base64.b64encode(gzip.compress(exp_bytes, compresslevel=9)).decode("ascii")
    genome_b64 = base64.b64encode(genome_cpp.encode("utf-8")).decode("ascii")

    termux_lines = [
        "#!/data/data/com.termux/files/usr/bin/bash",
        "set -e",
        'echo "======================================================================"',
        'echo "  NAP TOAN BO KINH NGHIEM & BO GEN TU DUY (__FORGED_COUNT__ THE CO) VAO STOCKFISH 19 PRO"',
        'echo "======================================================================"',
        "pkg install -y clang make binutils lld python tar gzip",
        "",
        "rm -rf ~/sf_dojo_inject && mkdir -p ~/sf_dojo_inject",
        'ARCHIVE=$(ls -t /sdcard/Download/Stockfish-19-Pro-Ultimate*.tar.gz /sdcard/Download/stockfish-19-pro*.tar.gz 2>/dev/null | head -n 1)',
        'if [ -z "$ARCHIVE" ] || [ ! -f "$ARCHIVE" ]; then',
        '  echo "Loi: Hay de file Stockfish-19-Pro-Ultimate-V3.tar.gz trong /sdcard/Download!"',
        "  exit 1",
        "fi",
        'tar -xzf "$ARCHIVE" --no-same-owner --no-same-permissions -C ~/sf_dojo_inject 2>/dev/null || true',
        'SRC_DIR=$(find ~/sf_dojo_inject -type f -name "search.cpp" | head -n 1 | xargs dirname)',
        'ROOT_DIR=$(dirname "$SRC_DIR")',
        'cd "$ROOT_DIR"',
        "",
        'NNUE_FILE=$(find ~/sf_dojo_inject -type f -name "nn-1a298aa575a0.nnue" -size +50M | head -n 1)',
        'mkdir -p "$ROOT_DIR/nnue" "$ROOT_DIR/experience"',
        'cp -f "$NNUE_FILE" "$SRC_DIR/nn-1a298aa575a0.nnue" 2>/dev/null || true',
        'cp -f "$NNUE_FILE" "$ROOT_DIR/nnue/nn-1a298aa575a0.nnue" 2>/dev/null || true',
        "",
        "base64 -d << 'EXP_EOF' | gzip -d > \"$ROOT_DIR/experience/experience.bin\"",
        "__EXP_GZ_B64__",
        "EXP_EOF",
        'cp -f "$ROOT_DIR/experience/experience.bin" "$SRC_DIR/experience.bin"',
        'cp -f "$ROOT_DIR/experience/experience.bin" /sdcard/Download/experience.bin',
        "",
        "base64 -d << 'GENOME_EOF' > \"$SRC_DIR/learned_genome.h\"",
        "__GENOME_B64__",
        "GENOME_EOF",
        "",
        "python3 - \"$ROOT_DIR/experience/experience.bin\" \"$SRC_DIR/learn.cpp\" << 'INJECT_PY'",
        "import re, sys",
        "from pathlib import Path",
        "exp_bytes = Path(sys.argv[1]).read_bytes()",
        "lc_path = Path(sys.argv[2])",
        'lc_txt = lc_path.read_text(encoding="utf-8")',
        'hex_lines = ["    " + ", ".join(f"0x{b:02x}" for b in exp_bytes[i:i+24]) + "," for i in range(0, len(exp_bytes), 24)]',
        'new_blob = f"alignas(8) static constexpr unsigned char EmbeddedExperienceBlob[{len(exp_bytes)}] = {\\n" + "\\n".join(hex_lines) + "\\n};"',
        'lc_txt = re.sub(r"alignas\\(8\\) static constexpr unsigned char EmbeddedExperienceBlob\\[\\d+\\] = \\{[\\s\\S]*?\\};", lambda _: new_blob, lc_txt, count=1)',
        'lc_path.write_text(lc_txt, encoding="utf-8")',
        'print(">>> Da nhung", (len(exp_bytes)-16)//24, "the co + Bo Gen Tu Duy LearnedSearchGenome vao src/learn.cpp!")',
        "INJECT_PY",
        "",
        "sed -i 's/-static-libstdc++//g' \"$SRC_DIR/Makefile\"",
        'make -C "$SRC_DIR" clean',
        'make -C "$SRC_DIR" -j$(nproc) build ARCH=armv8-dotprod COMP=ndk CXX=clang++ COMPCXX=clang++ EXTRALDFLAGS="-Wl,-z,max-page-size=16384"',
        'cp -f "$SRC_DIR/stockfish" "$ROOT_DIR/stockfish-19-pro-ultimate-v3-arm64-dotprod"',
        'cp -f "$SRC_DIR/stockfish" /sdcard/Download/stockfish-19-pro-ultimate-v3-arm64-dotprod',
        'make -C "$SRC_DIR" clean',
        'rm -f "$ROOT_DIR/benchmark/nn-1a298aa575a0.nnue" "$ROOT_DIR/baseline_src/nn-1a298aa575a0.nnue" "$ROOT_DIR/nn-1a298aa575a0.nnue"',
        'tar -czf /sdcard/Download/Stockfish-19-Pro-Ultimate-V3.tar.gz -C ~/sf_dojo_inject "$(basename "$ROOT_DIR")"',
        'ls -lh /sdcard/Download/stockfish-19-pro-ultimate-v3-arm64-dotprod /sdcard/Download/experience.bin /sdcard/Download/Stockfish-19-Pro-Ultimate-V3.tar.gz',
        'echo ">>> HOAN TAT! Engine cua ban da mang trong minh __FORGED_COUNT__ the co + Bo Gen Tu Duy moi nhat!"',
    ]
    termux_sh = (
        "\n".join(termux_lines)
        .replace("__FORGED_COUNT__", str(count))
        .replace("__EXP_GZ_B64__", exp_gz_b64)
        .replace("__GENOME_B64__", genome_b64)
        + "\n"
    )
    sh_path = output_dir / "termux_inject_forged_experience.sh"
    sh_path.write_text(termux_sh, encoding="utf-8")
    sh_path.chmod(0o755)

    # 7. Export comprehensive TRAINING_REPORT.md
    motif_rows = "\n".join(f"  - **{m}**: `{c}` đòn phản kích đã mổ xẻ & khắc sâu" for m, c in sorted(motif_counts.items(), key=lambda x: -x[1]))
    if not motif_rows:
        motif_rows = "  - *(Đang tích lũy qua các ván va chạm)*"

    genome_rows = "\n".join(
        f"| `{k}` | `{GENOME_SPEC[k][0]}` | **`{meta_learner.best_genome[k]}`** | {GENOME_SPEC[k][3]} |"
        for k in GENOME_SPEC
    )

    report_md = f"""# STOCKFISH 19 PRO — BÁO CÁO TỔNG HỢP TRI THỨC & TIẾN HÓA ĐA TẦNG (5H30P OMNISCIENT DOJO)

- **Thời gian rèn luyện thực tế**: `{stats['elapsed_str']}` / `{stats['target_str']}`
- **Số bàn va chạm đồng thời**: `{stats['concurrency']} bàn` (`{stats['threads']} luồng SMP/engine`, `MoveTime = {stats['move_time_ms']} ms/nước`)
- **Chế độ rèn luyện 4 tầng**: `{stats['mode']}` (Đối kháng Crucible + Tự phân cực Self-Play + Giải phẫu hậu chiến Depth-{stats['post_mortem_depth']} + Tiến hóa Meta-Learning `LearnedSearchGenome`)
- **Gói Engine đã tự động đóng gói lại**: {repackaged_tar_info}

## 1. Tầng 1 — Kho Kinh Nghiệm Thế Cờ & Chuỗi Sát Chiêu (`experience.bin` — Chuẩn `SF19EXP2`)
- **Số thế cờ khởi điểm**: `{stats['initial_entries']:,}` vị trí
- **Tổng số thế cờ sau rèn luyện**: **`{count:,}` vị trí** (`+{count - stats['initial_entries']:,}` thế cờ mới được đúc kết!)
- **Dung lượng tệp `experience.bin`**: **`{len(exp_bytes):,} bytes`** (`{len(exp_bytes)/1024:.1f} KB`)
- **Mã băm toàn vẹn SHA-256**: `{sha256_hex}`

## 2. Tầng 2 — Meta-Learning ("Học Cách Học" & Tiến Hóa Bộ Gen Tư Duy `learned_genome.h`)
Hệ thống Contextual Evolutionary Bandit đã thử nghiệm trực tiếp các đột biến tham số học & tìm kiếm qua từng ván đấu để chọn ra bộ gen chiến thắng tối ưu:

| Tham Số Tư Duy / Cách Học | Khởi Điểm | **Sau Tiến Hóa** | Ý Nghĩa Chiến Thuật & Cơ Chế Học |
| :--- | :---: | :---: | :--- |
{genome_rows}

## 3. Tầng 3 — Giải Phẫu Hậu Chiến & Phân Loại Mẫu Hình Chiến Thuật (`OMNISCIENT_EXPERIENCE_CODEX.json`)
- **Tổng số ván va chạm hoàn tất**: `{stats['games_played']}` ván
  - Va chạm đối kháng (`Pro vs Baseline`): `{stats['crucible_games']}` ván (`Pro Thắng: {stats['pro_wins']}`, `Hòa: {stats['draws']}`, `Baseline Thắng: {stats['sparring_wins']}`)
  - Tự va chạm phân cực (`Pro-Attacker vs Pro-Fortress Self-Play`): `{stats['selfplay_games']}` ván
- **Số chuỗi chiến thắng (Kill-Chains) thu hoạch trọn vẹn**: `{stats['kill_chains']}` chuỗi
- **Số bước ngoặt chiến thuật được Giải phẫu hậu chiến (Post-Mortem Depth {stats['post_mortem_depth']})**: **`{stats['surgeries_solved']}` thế cờ**
{motif_rows}

## 4. Tầng 4 — Hướng Dẫn Sử Dụng Gói Thành Phẩm Trên Termux
Trong gói Artifact **`Stockfish-Pro-Supreme-Experience-Bundle`** đã có sẵn:
1. **`Stockfish-19-Pro-Ultimate-V3.tar.gz`**: Bộ mã nguồn & kho kinh nghiệm đã được **tiêm tự động** toàn bộ `{count:,}` thế cờ mới + `learned_genome.h` mới nhất.
2. **`termux_inject_forged_experience.sh`**: Script 1 lệnh trên Termux để biên dịch ra binary `stockfish-19-pro-ultimate-v3-arm64-dotprod` nhúng sẵn mọi thứ:
```bash
sh /sdcard/Download/termux_inject_forged_experience.sh
```
"""
    (output_dir / "TRAINING_REPORT.md").write_text(report_md, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Stockfish 19 Pro 5h30m Omniscient Experience & Meta-Learning Dojo")
    parser.add_argument("--pro-bin", required=True, help="Path to Stockfish 19 Pro binary")
    parser.add_argument("--sparring-bin", required=True, help="Path to Sparring/Baseline binary")
    parser.add_argument("--seed-exp", required=True, help="Path to seed experience.bin")
    parser.add_argument("--output-dir", required=True, help="Directory to export all forged artifacts")
    parser.add_argument("--engine-src-dir", default="", help="Optional path to Stockfish-19-Pro-Ultimate-V3 root to auto-repackage tar.gz")
    parser.add_argument("--duration-minutes", type=float, default=330.0, help="Training duration in minutes (default 330 = 5h30m)")
    parser.add_argument("--concurrency", type=int, default=4, help="Number of simultaneous boards")
    parser.add_argument("--threads", type=int, default=1, help="Threads per engine instance")
    parser.add_argument("--move-time-ms", type=int, default=120, help="Move time per ply in ms")
    parser.add_argument("--post-mortem-depth", type=int, default=18, help="Depth for Post-Mortem Surgery")
    parser.add_argument("--mode", default="hybrid_all", help="Training mode: hybrid_all, crucible_vs_baseline, selfplay_persona")
    parser.add_argument("--max-games", type=int, default=0, help="Optional max games cap (0 = run until duration_minutes)")
    args = parser.parse_args()

    pro_bin = Path(args.pro_bin).resolve()
    sparring_bin = Path(args.sparring_bin).resolve()
    seed_exp = Path(args.seed_exp).resolve()
    output_dir = Path(args.output_dir).resolve()
    engine_src_dir = Path(args.engine_src_dir).resolve() if args.engine_src_dir else None
    output_dir.mkdir(parents=True, exist_ok=True)

    master_entries = load_experience_bin(seed_exp)
    initial_entries = len(master_entries)
    print(f"[OMNISCIENT DOJO] Kho kinh nghiệm khởi điểm: {initial_entries:,} thế cờ ({initial_entries * 24 + 16:,} bytes)")

    # Prepare per-worker experience & genome files
    worker_exp_paths: Dict[int, Path] = {}
    worker_genome_paths: Dict[int, Path] = {}
    for w in range(1, args.concurrency + 1):
        wp = output_dir / f"experience_worker_{w}.bin"
        save_experience_bin(master_entries, wp)
        worker_exp_paths[w] = wp
        gp = output_dir / f"genome_worker_{w}.ini"
        worker_genome_paths[w] = gp

    meta_learner = MetaGenomeLearner()
    for w in range(1, args.concurrency + 1):
        meta_learner.write_genome_ini(meta_learner.best_genome, worker_genome_paths[w])

    start_ts = time.time()
    deadline_ts = start_ts + args.duration_minutes * 60.0
    stop_requested = False

    def handle_sig(signum, frame):
        nonlocal stop_requested
        print(f"\n[OMNISCIENT DOJO] Nhận tín hiệu dừng ({signum}), đang lưu toàn bộ kinh nghiệm & đóng gói thành phẩm...")
        stop_requested = True

    signal.signal(signal.SIGINT, handle_sig)
    signal.signal(signal.SIGTERM, handle_sig)

    games_played = 0
    crucible_games = 0
    selfplay_games = 0
    pro_wins = 0
    draws = 0
    sparring_wins = 0
    kill_chains = 0
    surgeries_solved = 0
    critical_lessons: List[Dict] = []
    pgn_games: List[str] = []
    opening_stats: Dict[str, Dict[str, int]] = {}
    motif_counts: Dict[str, int] = {}

    def fmt_hms(sec: float) -> str:
        s = max(0, int(sec))
        return f"{s // 3600:02d}:{(s % 3600) // 60:02d}:{s % 60:02d}"

    next_game_idx = 1
    active_candidates: Dict[int, Dict[str, int]] = {}

    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        futures = {}
        for w in range(1, args.concurrency + 1):
            if args.max_games > 0 and next_game_idx > args.max_games:
                break
            cand = meta_learner.sample_candidate()
            active_candidates[w] = cand
            meta_learner.write_genome_ini(cand, worker_genome_paths[w])
            fut = pool.submit(
                play_and_learn_game,
                w,
                next_game_idx,
                pro_bin,
                sparring_bin,
                worker_exp_paths[w],
                worker_genome_paths[w],
                args.threads,
                args.move_time_ms,
                args.post_mortem_depth,
                args.mode,
            )
            futures[fut] = w
            next_game_idx += 1

        while futures:
            done_futs = []
            for fut in list(futures.keys()):
                if fut.done():
                    done_futs.append(fut)
            if not done_futs:
                time.sleep(0.05)
                continue

            for fut in done_futs:
                w = futures.pop(fut)
                try:
                    res = fut.result()
                    games_played += 1
                    gtype = res["game_type"]
                    res_str = res["result"]
                    op_name = res["opening"]
                    if op_name not in opening_stats:
                        opening_stats[op_name] = {"games": 0, "wins": 0, "draws": 0, "losses": 0, "surgeries": 0}
                    opening_stats[op_name]["games"] += 1
                    opening_stats[op_name]["surgeries"] += res["surgeries_count"]

                    if gtype == "CRUCIBLE_VS_BASELINE":
                        crucible_games += 1
                        if res["pro_score"] == 1.0:
                            pro_wins += 1
                            opening_stats[op_name]["wins"] += 1
                        elif res["pro_score"] == 0.0:
                            sparring_wins += 1
                            opening_stats[op_name]["losses"] += 1
                        else:
                            draws += 1
                            opening_stats[op_name]["draws"] += 1
                    else:
                        selfplay_games += 1
                        if res["pro_score"] == 1.0:
                            opening_stats[op_name]["wins"] += 1
                        elif res["pro_score"] == 0.0:
                            opening_stats[op_name]["losses"] += 1
                        else:
                            opening_stats[op_name]["draws"] += 1

                    if res_str in ("1-0", "0-1"):
                        kill_chains += 1
                    surgeries_solved += res["surgeries_count"]
                    for les in res["solved_lessons"]:
                        critical_lessons.append(les)
                        m_lbl = les.get("motif", "Tactical_Refutation")
                        motif_counts[m_lbl] = motif_counts.get(m_lbl, 0) + 1

                    # Merge worker experience into Hive-Mind master table
                    prev_count = len(master_entries)
                    w_entries = load_experience_bin(worker_exp_paths[w])
                    merge_experience_dicts(master_entries, w_entries)
                    new_entries_delta = max(0, len(master_entries) - prev_count)

                    # Sync updated Hive-Mind back to worker
                    save_experience_bin(master_entries, worker_exp_paths[w])

                    # Update Meta-Learner ("Learning How to Learn & Search")
                    cand_used = active_candidates.get(w, meta_learner.best_genome)
                    fitness = meta_learner.record_episode(
                        cand_used,
                        res["pro_score"],
                        res["plies"],
                        new_entries_delta,
                        res["surgeries_count"],
                        res["pro_blunders"],
                    )

                    # Record PGN
                    white_tag = "Stockfish-19-Pro" if res["pro_color"] == "White" else ("Stockfish-Sparring" if gtype == "CRUCIBLE_VS_BASELINE" else "Stockfish-19-Pro-Fortress")
                    black_tag = ("Stockfish-Sparring" if gtype == "CRUCIBLE_VS_BASELINE" else "Stockfish-19-Pro-Fortress") if res["pro_color"] == "White" else "Stockfish-19-Pro"
                    pgn_str = (
                        f'[Event "Stockfish 19 Pro 5h30m Omniscient Dojo ({gtype})"]\n'
                        f'[Round "{res["game_idx"]}"]\n'
                        f'[White "{white_tag}"]\n'
                        f'[Black "{black_tag}"]\n'
                        f'[Result "{res_str}"]\n'
                        f'[Opening "{op_name}"]\n'
                        f'[PlyCount "{res["plies"]}"]\n'
                        f'[MetaFitness "{fitness:.3f}"]\n\n'
                        f'{res["moves_uci"]} {res_str}'
                    )
                    pgn_games.append(pgn_str)

                    elapsed = time.time() - start_ts
                    print(
                        f"[DOJO G{res['game_idx']:04d} | { int(elapsed)//60:03d}m{int(elapsed)%60:02d}s] "
                        f"{gtype:<20} | {op_name[:34]:<34} | {res_str:<7} ({res['plies']:3d}p) | "
                        f"PostMortem: +{res['surgeries_count']} | Fit: {fitness:.2f} | Total Exp: {len(master_entries):,} entries",
                        flush=True,
                    )
                except Exception as e:
                    print(f"[WARN] Worker {w} exception: {e}", flush=True)

                # Schedule next game on this worker if within time and max_games
                now = time.time()
                can_continue = (not stop_requested) and (now + 8.0 < deadline_ts)
                if args.max_games > 0 and next_game_idx > args.max_games:
                    can_continue = False
                if can_continue:
                    cand = meta_learner.sample_candidate()
                    active_candidates[w] = cand
                    meta_learner.write_genome_ini(cand, worker_genome_paths[w])
                    new_fut = pool.submit(
                        play_and_learn_game,
                        w,
                        next_game_idx,
                        pro_bin,
                        sparring_bin,
                        worker_exp_paths[w],
                        worker_genome_paths[w],
                        args.threads,
                        args.move_time_ms,
                        args.post_mortem_depth,
                        args.mode,
                    )
                    futures[new_fut] = w
                    next_game_idx += 1

    elapsed_total = time.time() - start_ts
    stats = {
        "elapsed_sec": round(elapsed_total, 2),
        "elapsed_str": fmt_hms(elapsed_total),
        "target_str": fmt_hms(args.duration_minutes * 60.0),
        "concurrency": args.concurrency,
        "threads": args.threads,
        "move_time_ms": args.move_time_ms,
        "post_mortem_depth": args.post_mortem_depth,
        "mode": args.mode,
        "initial_entries": initial_entries,
        "games_played": games_played,
        "crucible_games": crucible_games,
        "selfplay_games": selfplay_games,
        "pro_wins": pro_wins,
        "draws": draws,
        "sparring_wins": sparring_wins,
        "kill_chains": kill_chains,
        "surgeries_solved": surgeries_solved,
    }

    export_all_artifacts(
        output_dir,
        master_entries,
        meta_learner,
        stats,
        critical_lessons,
        pgn_games,
        opening_stats,
        motif_counts,
        engine_source_dir=engine_src_dir,
    )

    # Clean up temporary per-worker files
    for w in range(1, args.concurrency + 1):
        worker_exp_paths[w].unlink(missing_ok=True)
        worker_genome_paths[w].unlink(missing_ok=True)

    print("=" * 84)
    print(f" HOÀN TẤT LÒ LUYỆN ĐA TẦNG! Tổng thế cờ: {len(master_entries):,} ({len(master_entries)*24+16:,} bytes)")
    print(f" Đã xuất trọn bộ Sổ tay Tri thức, Bộ Gen Tư Duy & Gói Đóng Gói tại: {output_dir}")
    print("=" * 84)


if __name__ == "__main__":
    main()
