"""
PersonaMem Converter

将 PersonaMem 数据集转换为 Locomo 格式。
"""
import json
import csv
import re
import ast
from collections import defaultdict
from pathlib import Path
from typing import Dict

from evaluation.src.converters.base import BaseConverter
from evaluation.src.converters.registry import register_converter


def extract_persona_name(system_content: str) -> str:
    """从 system message 中提取 persona 名字"""
    match = re.search(r'Name:\s*([^\n]+)', system_content)
    if match:
        return match.group(1).strip()
    return "User"


def clean_message_prefix(text: str) -> str:
    """清理消息中的 'User:' 和 'Assistant:' 前缀"""
    text = re.sub(r'^(User|Assistant):\s*', '', text, flags=re.MULTILINE)
    return text.strip()


# 注：不再需要类型转换，保留原始 question_type
# PersonaMem 有 7 种 question_type：
# - recall_user_shared_facts (129)
# - provide_preference_aligned_recommendations (55)
# - suggest_new_ideas (93)
# - recalling_the_reasons_behind_previous_updates (99)
# - track_full_preference_evolution (139)
# - generalizing_to_new_scenarios (57)
# - recalling_facts_mentioned_by_the_user (17)


def parse_options(options_str: str) -> Dict[str, str]:
    """解析 all_options 字符串，返回字典"""
    try:
        options_list = ast.literal_eval(options_str)
        options_dict = {}
        for opt in options_list:
            match = re.match(r'\(([a-z])\)\s*(.*)', opt, re.DOTALL)
            if match:
                key = f"({match.group(1)})"
                value = match.group(2).strip()
                options_dict[key] = value
        return options_dict
    except Exception as e:
        print(f"Warning: Failed to parse options: {e}")
        return {}


@register_converter("personamem")
class PersonaMemConverter(BaseConverter):
    """PersonaMem 数据集转换器"""
    
    def get_input_files(self) -> Dict[str, str]:
        """返回需要的输入文件"""
        return {
            "questions": "questions_32k.csv",
            "contexts": "shared_contexts_32k.jsonl"
        }
    
    def get_output_filename(self) -> str:
        """返回输出文件名"""
        return "personamem_32k_locomo_style.json"
    
    def convert(self, input_paths: Dict[str, str], output_path: str) -> None:
        """
        执行转换
        
        Args:
            input_paths: {
                "questions": "path/to/questions_32k.csv",
                "contexts": "path/to/shared_contexts_32k.jsonl"
            }
            output_path: 输出文件路径
        """
        print(f"🔄 Converting PersonaMem to Locomo format...")
        
        # 1. 读取 JSONL 文件，构建 context 字典
        print("   Loading shared contexts...")
        contexts = {}
        with open(input_paths["contexts"], 'r', encoding='utf-8') as f:
            for line in f:
                data = json.loads(line)
                contexts.update(data)
        print(f"   Loaded {len(contexts)} shared contexts")
        
        # 2. 读取 CSV 文件
        print("   Loading questions...")
        questions = []
        with open(input_paths["questions"], 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            questions = list(reader)
        print(f"   Loaded {len(questions)} questions")
        
        # 3. 按 (shared_context_id, end_index_in_shared_context) 分组
        print("   Grouping questions...")
        grouped_questions = defaultdict(list)
        for q in questions:
            key = (q['shared_context_id'], int(q['end_index_in_shared_context']))
            grouped_questions[key].append(q)
        print(f"   Grouped into {len(grouped_questions)} unique context groups")
        
        # 4. 转换为 Locomo 格式
        print("   Converting to Locomo format...")
        locomo_data = []
        
        for (context_id, end_index), question_list in grouped_questions.items():
            # 获取对应的 context
            if context_id not in contexts:
                print(f"   Warning: context_id {context_id} not found")
                continue
            
            full_context = contexts[context_id]
            context_messages = full_context[:end_index + 1]
            
            # 提取 persona 名字
            persona_name = "User"
            assistant_name = "Assistant"
            if context_messages and context_messages[0]['role'] == 'system':
                persona_name = extract_persona_name(context_messages[0]['content'])
            
            # 创建 Locomo 条目
            locomo_entry = {
                "qa": [],
                "conversation": {
                    "speaker_a": persona_name,
                    "speaker_b": assistant_name,
                    "session_0_date_time": "Unknown",  # PersonaMem 没有时间信息
                    "session_0": []
                }
            }
            
            # 添加所有问题到 qa 列表
            for q in question_list:
                options = parse_options(q['all_options'])
                correct_answer_text = options.get(q['correct_answer'], q['correct_answer'])
                
                qa_item = {
                    "question_id": q['question_id'],
                    "question": q['user_question_or_message'],
                    "answer": q['correct_answer'],
                    "answer_text": correct_answer_text,
                    "all_options": options,
                    "evidence": [],
                    "category": q['question_type'],  # 保留原始类型，不做转换
                    "topic": q['topic'],
                    "persona_id": q['persona_id'],
                    "context_length_in_tokens": int(q['context_length_in_tokens']),
                    "distance_to_ref_in_tokens": int(q['distance_to_ref_in_tokens']),
                }
                locomo_entry["qa"].append(qa_item)
            
            # 构建对话列表
            dialogue_idx = 0
            for msg in context_messages:
                if msg['role'] == 'system':
                    continue  # 跳过 system message
                
                speaker = persona_name if msg['role'] == 'user' else assistant_name
                cleaned_text = clean_message_prefix(msg['content'])
                
                dialogue_item = {
                    "speaker": speaker,
                    "text": cleaned_text,
                    "dia_id": f"D0:{dialogue_idx}"
                }
                locomo_entry["conversation"]["session_0"].append(dialogue_item)
                dialogue_idx += 1
            
            locomo_data.append(locomo_entry)
        
        # 5. 保存结果
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(locomo_data, f, indent=2, ensure_ascii=False)
        
        print(f"   ✅ Saved {len(locomo_data)} entries to {output_path}")
        print(f"   Total questions: {sum(len(entry['qa']) for entry in locomo_data)}")

