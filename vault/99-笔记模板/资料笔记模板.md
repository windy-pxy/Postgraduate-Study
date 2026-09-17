---
id: "{{id}}"
type: source-note
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
source_file: "{{source_file}}"
---

# {{title}}

<!-- 复制到正式笔记目录后填写：id 须唯一；删除未用的占位符，未知来源字段设为空，空列表用 []。type 为此模板的固定结构常量。公式使用 LaTeX；不得猜测知识、页码或成绩。 -->

## 来源记录

{{source_name_and_edition}}

## 原始文件与页码

原始文件：`{{source_file}}`

原件页码：{{source_page}}

{{optional_pdf_page_index}}

## 原文摘录

{{verified_excerpt_with_page}}

## 资料要点

{{source_summary_with_page}}

## 我的理解

{{my_understanding}}

## 关联知识点

[[{{knowledge_note_path}}]]

{{source_knowledge_relation}}

## 待核实内容

{{unverified_items}}
