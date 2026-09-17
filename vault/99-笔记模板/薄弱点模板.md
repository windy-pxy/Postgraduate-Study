---
id: "{{id}}"
type: weakness
course: "{{course}}"
subject: "{{subject}}"
chapter: "{{chapter}}"
knowledge_points:
  - "[[{{knowledge_note_path}}]]"
source_type: "{{source_type}}"
source_name: "{{source_name}}"
source_page: "{{source_page}}"
difficulty: "{{difficulty}}"
mastery: "{{mastery}}"
status: "{{status}}"
created: "{{created}}"
updated: "{{updated}}"
review_dates:
  - "{{review_date}}"
tags:
  - "{{tag}}"
---

# {{title}}

<!-- 复制到正式笔记目录后填写：id 须唯一；删除未用的占位符，未知来源字段设为空，空列表用 []。type 为此模板的固定结构常量。公式使用 LaTeX；不得猜测知识、页码或成绩。 -->

## 薄弱知识点

[[{{knowledge_note_path}}]]

## 证据

[[{{mistake_or_test_note_path}}]]

{{evidence_description}}

## 出现次数

{{verified_occurrence_count}}

## 最近错误

{{latest_error_date_and_note}}

## 掌握程度

{{mastery}}

{{mastery_evidence}}

## 改进计划

{{improvement_plan}}

## 复查记录

{{recheck_date_and_result}}
