import 'package:flutter/material.dart';

import 'normal_day_context.dart';
import 'theme.dart';

/// Androidと閲覧ページ、候補一覧と台詳細で共用する曜日の補足。
class NormalDayContextNote extends StatelessWidget {
  const NormalDayContextNote({super.key, required this.contextInfo});

  final NormalDayContext contextInfo;

  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsets.symmetric(vertical: 8),
    child: Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          contextInfo.title,
          style: const TextStyle(fontSize: 13, fontWeight: FontWeight.w600),
        ),
        const SizedBox(height: 4),
        Text(
          contextInfo.body,
          style: const TextStyle(
            fontSize: 12,
            color: AppColors.ash,
            height: 1.45,
          ),
        ),
        const ExpansionTile(
          tilePadding: EdgeInsets.zero,
          title: Text('曜日傾向の根拠と限界', style: TextStyle(fontSize: 12)),
          children: [
            Padding(
              padding: EdgeInsets.only(bottom: 12),
              child: Text(
                normalDayContextEvidence,
                style: TextStyle(
                  fontSize: 12,
                  color: AppColors.ash,
                  height: 1.5,
                ),
              ),
            ),
          ],
        ),
      ],
    ),
  );
}
