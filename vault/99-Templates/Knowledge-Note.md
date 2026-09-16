---
id: "{{id}}"
type: knowledge
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

## 核心定义

{{core_definition}}

## 通俗理解

{{plain_explanation}}

## 前置知识

[[{{prerequisite_note_path}}]]

{{prerequisite_relation}}

## 核心结论

{{key_conclusions}}

## 数学公式或工作原理

{{latex_formula_or_working_principle}}

## 考研考法

{{exam_patterns_with_evidence}}

## 解题方法

{{solution_methods}}

## 易错点

{{common_errors_with_evidence}}

## 关联知识

[[{{related_knowledge_note_path}}]]

{{semantic_relation}}

## 对应真题

[[{{past_paper_note_path}}]]

## 我的理解

{{my_understanding}}

## 待解决问题

{{open_questions}}
