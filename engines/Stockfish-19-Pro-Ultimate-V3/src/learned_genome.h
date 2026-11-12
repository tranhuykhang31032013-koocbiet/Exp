/*
  Stockfish 19-Pro Ultimate V7.5 — Omniscient Meta-Learning & Search Genome
  Auto-forged and continuously evolved by the 5h30m Multi-Board Experience Dojo.
*/

#ifndef LEARNED_GENOME_H_INCLUDED
#define LEARNED_GENOME_H_INCLUDED

namespace Stockfish {

struct LearnedSearchGenome {
    int tdLambdaDecayPermille        = 944   ; // Hệ số truyền ngược TD-Lambda qua từng nước cờ (permille)
    int tdBlendTrajectoryWeight      = 57    ; // Tỷ trọng kết quả cuối ván so với đánh giá cục bộ (%)
    int winRewardBoost               = 336   ; // Biên độ thưởng khắc sâu chuỗi nước chiến thắng
    int lossPenaltyMagnitude         = 340   ; // Biên độ phạt triệt tiêu nhánh dẫn tới thất bại
    int drawStagnationPenalty        = 22    ; // Mức phạt chống lặp lại các biến hòa vô bổ để tự mở lối đi mới
    int pvHarvestMaxHorizon          = 5     ; // Số ply nhánh biến chính (PV) thu hoạch tự động trong lúc suy nghĩ
    int killerBookEvalMargin         = 54    ; // Biên độ bảo vệ nước đi Sát Thủ trong kho kinh nghiệm (Internal Value)
    int standardBookEvalMargin       = 30    ; // Biên độ bảo vệ nước đi kinh nghiệm tiêu chuẩn
    int rootHistoryKillerBoost       = 976   ; // Xung lực lịch sử ưu tiên nhánh Killer tại gốc
    int lookaheadHorizonBoost1       = 489   ; // Xung lực lịch sử nhìn trước 1 ply từ kho kinh nghiệm
    int lookaheadHorizonBoost2       = 464   ; // Xung lực lịch sử nhìn trước 2 ply từ kho kinh nghiệm
    int refutedMoveHistoryPenalty    = -960  ; // Mức phạt lịch sử khóa chặt các nước đi đã từng bị phản bác
    int inTreeTtInjectMinPerf        = 175   ; // Ngưỡng hiệu suất tối thiểu để tiêm thẳng nước cờ vào bảng băm TT
    int openingOptimismSkew          = 4     ; // Độ sắc bén công kích giai đoạn Khai cuộc
    int middlegameOptimismSkew       = 8     ; // Độ sắc bén công kích giai đoạn Trung cuộc phức tạp
    int endgameOptimismSkew          = 4     ; // Độ chính xác chuyển hóa ưu thế giai đoạn Tàn cuộc
    int winningContemptPress         = 19    ; // Áp lực từ chối hòa khi đang nắm ưu thế
    int defendingContemptBailout     = -15   ; // Chủ động tìm biến đỡ hòa khi thế trận bất lợi
    int overdriveHeavyMaterialMul    = 3465  ; // Hệ số đốt công suất tính toán ở trung cuộc nhiều quân (permille)
    int overdriveTacticalSwingMul    = 2568  ; // Hệ số đốt công suất khi thế trận biến động chiến thuật (permille)
    int complexTensionBonus          = 6     ; // Thưởng giữ sức căng đa quân trên bàn cờ
    int initiativeMomentumStep       = 3     ; // Bước nhảy xung lực khi liên tục gia tăng ưu thế
    int maxAdaptiveMomentum          = 11    ; // Biên độ xung lực thích ứng tối đa trong ván đấu
};

inline constexpr LearnedSearchGenome CompiledLearnedGenome{};

}  // namespace Stockfish

#endif  // LEARNED_GENOME_H_INCLUDED
