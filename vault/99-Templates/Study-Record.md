---
id: "{{id}}"
type: study-record
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

## 日期

{{study_date}}

## 学习内容

{{actual_study_content_and_links}}

## 时长

{{duration_minutes}} 分钟

## 完成情况

{{actual_completion}}

## 新增错题

[[{{mistake_note_path}}]]

## 次日计划

{{next_day_plan}}
