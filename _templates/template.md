$templateContent = @"
---
service_name: ""
description: ""
inputs:
  - source: ""
    data_format: ""
    schema: ""
outputs:
  - target: ""
    data_format: ""
    schema: ""
---

## 概要

(ここにコンポーネントの概要を記述)

## 詳細

(ここに処理の詳細や仕様を記述)
"@

Set-Content -Path "_templates/template.md" -Value $templateContent