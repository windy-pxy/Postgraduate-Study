---
id: "{{id}}"
type: mistake
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
error_type: "{{error_type}}"
---

# {{title}}

<!-- 复制到正式笔记目录后填写：id 须唯一；删除未用的占位符，未知来源字段设为空，空列表用 []。type 为此模板的固定结构常量。公式使用 LaTeX；不得猜测知识、页码或成绩。 -->

## 原题

{{original_question_with_source_page}}

## 我的答案

{{my_answer}}

## 正确答案

{{verified_answer_and_source}}

## 错误位置

{{error_location}}

## 错误类型

{{error_type}}

<!-- 固定选项：concept、calculation、method、reading、memory、careless、unknown。 -->

## 根本原因

{{root_cause}}

## 正确方法

{{correct_method}}

## 一题多解

{{alternative_solutions}}

## 关联知识点

[[{{knowledge_note_path}}]]

{{error_knowledge_relation}}

## 同类题

[[{{similar_question_note_path}}]]

{{similarity_evidence}}

## 复习记录

{{review_date_and_result}}

## 是否再次做对

{{retest_result_and_date}}
