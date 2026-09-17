---
id: "{{id}}"
type: past-paper
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

## 试卷与题号

{{exam_year_and_question_number}}

## 原始来源与页码

{{original_file_name_and_page}}

## 所属章节

{{verified_chapter}}

## 题目

{{original_question}}

## 我的答案

{{my_answer}}

## 参考答案与依据

{{verified_answer_with_source_page}}

## 解题过程

{{solution_steps}}

## 关联知识点

[[{{knowledge_note_path}}]]

## 错题记录

[[{{mistake_note_path}}]]

## 复习记录

{{review_date_and_result}}
