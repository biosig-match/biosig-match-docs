---
service_name: "RabbitMQ"
description: "各マイクロサービス間を疎結合で繋ぐ、高性能なメッセージブローカー。"
inputs:
  - source: "Collectorサービス"
    data_format: "AMQP Message"
    schema: "Body: バイナリデータ, Headers: { user_id }"
outputs:
  - target: "Processorサービス, Realtime Analyzerサービス"
    data_format: "AMQP Message"
    schema: "同上"
---

## 概要

RabbitMQ は、本システムにおける情報のハブとして機能します。特に`raw_data_exchange`という名前の**Fanout Exchange**を利用することで、`Collector`から発行された単一のメッセージを、関心を持つ全てのサービス（`Processor`と`Realtime Analyzer`）に同時に、かつ独立して配信します。

## 詳細

- **採用技術**: Fanout Exchange
- **Exchange 名**: `raw_data_exchange`
- **バインドされるキュー**:
  - `processing_queue` (`Processor`サービスが購読)
  - `analysis_queue` (`Realtime Analyzer`サービスが購読)
- **背景**: Fanout Exchange を採用した理由は、**サービスの完全な分離**を実現するためです。
  - **独立性**: `Processor`がデータベースへの書き込みで遅延しても、`Realtime Analyzer`のリアルタイム処理には一切影響しません。逆も同様です。
  - **耐障害性**: 片方のサービスがダウンしても、もう片方はメッセージを受信し続け、処理を継続できます。
  - **拡張性**: 将来、生データを必要とする新しいサービス（例: 異常検知サービス）を追加したくなった場合、既存の構成に一切変更を加えることなく、新しいキューを`raw_data_exchange`にバインドするだけで機能拡張が可能です。これにより、システム全体の柔軟性と保守性が大幅に向上します。
