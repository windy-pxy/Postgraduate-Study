---
id: "{{id}}"
type: stage-test
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

## 试卷范围

{{test_scope}}

## 题目

{{test_questions}}

## 答案

{{verified_answers}}

## 得分

{{score}} / {{max_score}}

## 耗时

{{duration_minutes}} 分钟

## 错误分布

{{error_distribution_with_evidence}}

## 薄弱点

[[{{weakness_note_path}}]]

{{weakness_evidence}}

## 后续复习

{{review_plan}}
