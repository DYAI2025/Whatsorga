"""性能测试脚本 - 测试记忆提取各单元的耗时

测试各个记忆提取单元的耗时，包括：
- MemCell 提取
- Episode Memory 提取
- Profile Memory 提取
- Semantic Memory 提取
- Event Log 提取

使用方法:
    uv run python src/bootstrap.py demo/performance_test.py
"""

import asyncio
import time
from datetime import datetime, timedelta
from typing import Dict, List
from dataclasses import dataclass

from memory_layer.memory_manager import MemoryManager
from memory_layer.memcell_extractor.base_memcell_extractor import RawData
from memory_layer.types import RawDataType, MemoryType, MemCell
from common_utils.datetime_utils import get_now_with_timezone
import uuid


@dataclass
class PerformanceResult:
    """性能测试结果"""
    step_name: str
    duration_ms: float
    success: bool
    details: str = ""


class PerformanceTester:
    """性能测试器"""
    
    def __init__(self):
        self.memory_manager = MemoryManager()
        self.results: List[PerformanceResult] = []
        self.test_messages = self._create_test_messages()
    
    def _create_test_messages(self) -> List[RawData]:
        """创建测试用的对话消息 - 使用更多消息以确保触发边界检测"""
        base_time = get_now_with_timezone()
        messages = []
        
        # 创建多轮对话，使用更多消息和更大的时间间隔来触发边界检测
        # 第一段对话：关于工作的话题
        conversation_data = [
            {
                "speaker_id": "user_001",
                "content": "我最近在考虑换工作，想找一个更好的发展机会",
                "timestamp": (base_time - timedelta(hours=2)).isoformat()
            },
            {
                "speaker_id": "assistant",
                "content": "听起来是个重要的决定。你目前的工作有什么不满意的吗？",
                "timestamp": (base_time - timedelta(hours=2, minutes=-58)).isoformat()
            },
            {
                "speaker_id": "user_001",
                "content": "主要是薪资和成长空间，现在的工作比较稳定但缺乏挑战",
                "timestamp": (base_time - timedelta(hours=2, minutes=-56)).isoformat()
            },
            {
                "speaker_id": "assistant",
                "content": "理解。你希望新工作能提供什么样的机会？",
                "timestamp": (base_time - timedelta(hours=2, minutes=-54)).isoformat()
            },
            {
                "speaker_id": "user_001",
                "content": "我希望能在技术上有更多突破，同时薪资能提升30%以上",
                "timestamp": (base_time - timedelta(hours=2, minutes=-52)).isoformat()
            },
            {
                "speaker_id": "assistant",
                "content": "很好的目标。你目前的技术栈是什么？",
                "timestamp": (base_time - timedelta(hours=2, minutes=-50)).isoformat()
            },
            {
                "speaker_id": "user_001",
                "content": "我主要做Python后端开发，熟悉Django和FastAPI，对AI和机器学习也很感兴趣",
                "timestamp": (base_time - timedelta(hours=2, minutes=-48)).isoformat()
            },
            {
                "speaker_id": "assistant",
                "content": "你的技能组合很有竞争力。建议你关注AI相关的岗位，这个领域发展很快",
                "timestamp": (base_time - timedelta(hours=2, minutes=-46)).isoformat()
            },
            {
                "speaker_id": "user_001",
                "content": "谢谢建议，我会认真考虑的。另外我想了解一下，你们公司有AI相关的职位吗？",
                "timestamp": (base_time - timedelta(hours=2, minutes=-44)).isoformat()
            },
            {
                "speaker_id": "assistant",
                "content": "有的，我们正在招聘AI工程师。如果你感兴趣，我可以帮你推荐",
                "timestamp": (base_time - timedelta(hours=2, minutes=-42)).isoformat()
            },
            {
                "speaker_id": "user_001",
                "content": "太好了！那我需要准备什么材料？",
                "timestamp": (base_time - timedelta(hours=2, minutes=-40)).isoformat()
            },
            {
                "speaker_id": "assistant",
                "content": "需要简历和作品集，特别是AI相关的项目经验。你可以先准备一下，然后我们再详细讨论",
                "timestamp": (base_time - timedelta(hours=2, minutes=-38)).isoformat()
            },
            {
                "speaker_id": "user_001",
                "content": "好的，我会尽快准备的。谢谢你的帮助！",
                "timestamp": (base_time - timedelta(hours=2, minutes=-36)).isoformat()
            },
            {
                "speaker_id": "assistant",
                "content": "不客气，祝你好运！",
                "timestamp": (base_time - timedelta(hours=2, minutes=-34)).isoformat()
            },
            # 第二段对话：新话题开始（时间间隔1小时，应该触发边界）
            {
                "speaker_id": "user_001",
                "content": "你好，我想咨询一下关于健康管理的问题",
                "timestamp": (base_time - timedelta(hours=1)).isoformat()  # 时间间隔1小时
            },
            {
                "speaker_id": "assistant",
                "content": "好的，我很乐意帮助您。请告诉我您想了解哪方面的健康管理？",
                "timestamp": (base_time - timedelta(hours=1, minutes=-58)).isoformat()
            },
            {
                "speaker_id": "user_001",
                "content": "我最近感觉工作压力很大，经常失眠，想了解一下如何改善",
                "timestamp": (base_time - timedelta(hours=1, minutes=-56)).isoformat()
            },
            {
                "speaker_id": "assistant",
                "content": "工作压力导致的失眠确实需要重视。建议您可以尝试规律作息、适度运动、放松训练等方法",
                "timestamp": (base_time - timedelta(hours=1, minutes=-54)).isoformat()
            },
            {
                "speaker_id": "user_001",
                "content": "具体应该怎么做呢？",
                "timestamp": (base_time - timedelta(hours=1, minutes=-52)).isoformat()
            },
            {
                "speaker_id": "assistant",
                "content": "首先，建议您每天固定时间睡觉和起床，建立规律的作息。其次，可以在睡前进行深呼吸或冥想练习。另外，避免在睡前使用电子设备",
                "timestamp": (base_time - timedelta(hours=1, minutes=-50)).isoformat()
            },
        ]
        
        for idx, msg in enumerate(conversation_data):
            raw_data = RawData(
                content=msg,
                data_id=f"msg_{idx:03d}",
                data_type=RawDataType.CONVERSATION,
                metadata={"group_id": "test_group_001"}
            )
            messages.append(raw_data)
        
        return messages
    
    
    async def _measure_time(self, step_name: str, coro):
        """测量异步操作的耗时"""
        start_time = time.time()
        try:
            result = await coro
            duration_ms = (time.time() - start_time) * 1000
            self.results.append(PerformanceResult(
                step_name=step_name,
                duration_ms=duration_ms,
                success=True,
                details=f"成功: {type(result).__name__}"
            ))
            return result
        except Exception as e:
            duration_ms = (time.time() - start_time) * 1000
            self.results.append(PerformanceResult(
                step_name=step_name,
                duration_ms=duration_ms,
                success=False,
                details=f"失败: {str(e)}"
            ))
            raise
    
    async def test_memcell_extraction(self):
        """测试 MemCell 提取耗时 - 只提取 MemCell，不提取下游记忆"""
        print("\n" + "="*80)
        print("📊 测试 1: MemCell 提取（仅 MemCell，不提取下游记忆）")
        print("="*80)
        
        # 将消息分为历史消息和新消息
        # 前14条作为历史（第一段对话），后6条作为新消息（第二段对话，时间间隔1小时，应该触发边界）
        history_messages = self.test_messages[:14]
        new_messages = self.test_messages[14:]
        
        print(f"  历史消息数: {len(history_messages)}")
        print(f"  新消息数: {len(new_messages)}")
        print(f"  💡 模拟真实场景: 新消息将逐条处理（每次只传入1条）")
        print(f"  ⚙️  配置: 禁用语义记忆和事件日志提取，只提取基础 MemCell")
        
        # 逐条处理新消息，模拟真实使用场景
        memcell = None
        cumulative_history = history_messages.copy()
        message_timings = []  # 记录每条消息的耗时
        
        print(f"\n  📝 开始逐条处理新消息...")
        
        for idx, new_msg in enumerate(new_messages, 1):
            print(f"\n  --- 处理第 {idx} 条新消息 ---")
            msg_start = time.time()
            
            # 每次只传入一条新消息
            single_new_message = [new_msg]
            
            # 提取消息内容预览
            msg_content = ""
            if hasattr(new_msg, 'content'):
                if isinstance(new_msg.content, dict):
                    msg_content = new_msg.content.get("content", "")
                else:
                    msg_content = str(new_msg.content)
            msg_content_preview = msg_content[:50] if msg_content else ""
            
            print(f"     消息内容: {msg_content_preview}...")
            
            # 只提取 MemCell，禁用下游记忆提取
            memcell, status_result = await self.memory_manager.extract_memcell(
                history_raw_data_list=cumulative_history,
                new_raw_data_list=single_new_message,  # 只传入一条新消息
                raw_data_type=RawDataType.CONVERSATION,
                group_id="test_group_001",
                group_name="测试群组",
                user_id_list=["user_001"],
                enable_semantic_extraction=False,  # 禁用语义记忆提取
                enable_event_log_extraction=False,  # 禁用事件日志提取
            )
            
            msg_duration = (time.time() - msg_start) * 1000
            message_timings.append({
                "index": idx,
                "duration": msg_duration,
                "memcell_extracted": memcell is not None,
                "should_wait": status_result.should_wait if status_result else None,
                "content_preview": msg_content_preview,
                "memcell": memcell  # 保存 MemCell 以便后续提取记忆
            })
            
            print(f"     ⏱️  耗时: {msg_duration:.2f} ms ({msg_duration/1000:.2f} 秒)")
            print(f"     📊 状态: {'✅ MemCell已提取' if memcell else '⏳ 继续等待'}")
            
            # 如果 MemCell 被提取，打印基本信息
            if memcell:
                print(f"     🎯 边界检测成功，MemCell已提取！")
                print(f"     Event ID: {memcell.event_id}")
                
                # 打印 MemCell 基本信息（注意：已禁用下游记忆提取）
                print(f"\n     📋 MemCell 基本信息:")
                print(f"        - Event ID: {memcell.event_id}")
                print(f"        - Summary: {memcell.summary[:100] if memcell.summary else 'N/A'}...")
                print(f"        - Subject: {memcell.subject[:100] if memcell.subject else 'N/A'}...")
                print(f"        - Episode: {'有' if memcell.episode else '无'} ({len(memcell.episode) if memcell.episode else 0} 字符)")
                print(f"        - 参与者: {', '.join(memcell.participants) if memcell.participants else 'N/A'}")
                print(f"        - 时间戳: {memcell.timestamp}")
                
                # 确认下游记忆未提取
                print(f"\n     ✅ 确认: 下游记忆未提取（将在后续测试中单独提取）")
                print(f"        - Semantic Memory: {'有' if hasattr(memcell, 'semantic_memories') and memcell.semantic_memories else '无'}")
                print(f"        - Event Log: {'有' if hasattr(memcell, 'event_log') and memcell.event_log else '无'}")
                
                break
            
            # 如果 MemCell 未提取，将当前消息加入历史，继续处理下一条
            cumulative_history.append(new_msg)
        
        # 计算总耗时
        total_duration = sum(t["duration"] for t in message_timings)
        
        # 记录总耗时
        self.results.append(PerformanceResult(
            step_name="MemCell 提取 (逐条处理总计)",
            duration_ms=total_duration,
            success=memcell is not None,
            details=f"处理了 {len(message_timings)} 条消息，{'成功提取' if memcell else '未提取'}"
        ))
        
        # 打印每条消息的耗时统计
        print(f"\n  📊 逐条消息耗时统计:")
        print(f"     {'消息序号':<10} {'耗时 (ms)':<15} {'耗时 (秒)':<12} {'状态':<15} {'内容预览':<30}")
        print(f"     {'-'*10} {'-'*15} {'-'*12} {'-'*15} {'-'*30}")
        
        for timing in message_timings:
            status = "✅ 已提取" if timing["memcell_extracted"] else "⏳ 等待中"
            content = timing["content_preview"] + "..." if len(timing["content_preview"]) > 27 else timing["content_preview"]
            print(f"     第{timing['index']:2d}条    {timing['duration']:>12.2f} ms  {timing['duration']/1000:>10.2f} 秒  {status:<15} {content:<30}")
        
        if message_timings:
            avg_duration = sum(t["duration"] for t in message_timings) / len(message_timings)
            min_duration = min(t["duration"] for t in message_timings)
            max_duration = max(t["duration"] for t in message_timings)
            
            print(f"\n  📈 统计信息:")
            print(f"     - 处理消息数: {len(message_timings)} 条")
            print(f"     - 总耗时: {total_duration:.2f} ms ({total_duration/1000:.2f} 秒)")
            print(f"     - 平均每条消息耗时: {avg_duration:.2f} ms ({avg_duration/1000:.2f} 秒)")
            print(f"     - 最快: {min_duration:.2f} ms ({min_duration/1000:.2f} 秒)")
            print(f"     - 最慢: {max_duration:.2f} ms ({max_duration/1000:.2f} 秒)")
        
        if memcell:
            print(f"\n  ✅ MemCell 提取成功（仅 MemCell，不含下游记忆）")
            print(f"  Event ID: {memcell.event_id}")
            print(f"  Episode 长度: {len(memcell.episode) if memcell.episode else 0} 字符")
            print(f"  语义记忆: {'有' if hasattr(memcell, 'semantic_memories') and memcell.semantic_memories else '无'}")
            print(f"  事件日志: {'有' if hasattr(memcell, 'event_log') and memcell.event_log else '无'}")
            
            # 分析触发 MemCell 提取的那条消息
            extracted_msg_timing = next((t for t in message_timings if t["memcell_extracted"]), None)
            if extracted_msg_timing:
                print(f"\n  🎯 触发提取的消息分析:")
                print(f"     - 触发消息序号: 第 {extracted_msg_timing['index']} 条")
                print(f"     - 触发消息耗时: {extracted_msg_timing['duration']:.2f} ms ({extracted_msg_timing['duration']/1000:.2f} 秒)")
                print(f"     - 该消息包含: 边界检测 + Episode提取（语义记忆和事件日志已禁用）")
                
                # 估算该消息各子步骤耗时（仅 MemCell 提取）
                trigger_steps = {
                    "边界检测 (LLM调用)": extracted_msg_timing['duration'] * 0.20,
                    "Episode提取 (LLM调用)": extracted_msg_timing['duration'] * 0.70,
                    "向量化 (Embedding)": extracted_msg_timing['duration'] * 0.10,
                }
                
                print(f"\n  📈 触发消息的子步骤耗时（估算）:")
                for step_name, step_time in trigger_steps.items():
                    percentage = (step_time / extracted_msg_timing['duration']) * 100
                    print(f"     - {step_name:<35} {step_time:>10.2f} ms ({percentage:>5.2f}%)")
            
            return memcell
        else:
            print(f"  ❌ MemCell 未提取 (should_wait: {status_result.should_wait if status_result else 'N/A'})")
            print(f"  💡 说明:")
            print(f"     - 边界检测已完成，耗时已记录")
            print(f"     - 系统判断当前对话未达到边界，继续累积消息")
            print(f"     - 端到端测试需要真实的 MemCell，无法继续后续测试")
            print(f"  🔄 建议: 增加更多消息或调整时间间隔以触发边界检测")
            return None
    
    async def test_episode_memory_extraction(self, memcell):
        """测试 Episode Memory 提取耗时"""
        if not memcell:
            print("\n" + "="*80)
            print("⏭️  跳过: Episode Memory 提取 (需要 MemCell)")
            print("="*80)
            return None
        
        print("\n" + "="*80)
        print("📊 测试 2: Episode Memory 提取")
        print("="*80)
        print(f"  基于 MemCell: {memcell.event_id}")
        
        episode_memories = await self._measure_time(
            "Episode Memory 提取",
            self.memory_manager.extract_memory(
                memcell_list=[memcell],
                memory_type=MemoryType.EPISODE_SUMMARY,
                user_ids=["user_001"],
                group_id="test_group_001",
                group_name="测试群组",
            )
        )
        
        if episode_memories:
            print(f"\n  ✅ Episode Memory 提取成功")
            print(f"  提取数量: {len(episode_memories)}")
            for idx, ep in enumerate(episode_memories, 1):
                print(f"\n  📝 Episode {idx}:")
                print(f"     - User ID: {ep.user_id}")
                print(f"     - Subject: {ep.subject[:100] if ep.subject else 'N/A'}...")
                print(f"     - Summary: {ep.summary[:150] if ep.summary else 'N/A'}...")
                print(f"     - Episode: {ep.episode[:200] if ep.episode else 'N/A'}...")
                print(f"     - 时间戳: {ep.timestamp}")
        else:
            print(f"  ⚠️ Episode Memory 未提取")
        
        return episode_memories[0] if episode_memories else None
    
    async def test_profile_memory_extraction(self, memcell):
        """测试 Profile Memory 提取耗时"""
        if not memcell:
            print("\n" + "="*80)
            print("⏭️  跳过: Profile Memory 提取 (需要 MemCell)")
            print("="*80)
            return None
        
        print("\n" + "="*80)
        print("📊 测试 3: Profile Memory 提取")
        print("="*80)
        print(f"  基于 MemCell: {memcell.event_id}")
        
        profile_memories = await self._measure_time(
            "Profile Memory 提取",
            self.memory_manager.extract_memory(
                memcell_list=[memcell],
                memory_type=MemoryType.PROFILE,
                user_ids=["user_001"],
                group_id="test_group_001",
            )
        )
        
        if profile_memories:
            print(f"\n  ✅ Profile Memory 提取成功")
            print(f"  提取数量: {len(profile_memories)}")
            for idx, profile in enumerate(profile_memories, 1):
                print(f"\n  📝 Profile {idx}:")
                print(f"     - User ID: {profile.user_id}")
                print(f"     - Memory Type: {profile.memory_type.value if hasattr(profile, 'memory_type') else 'N/A'}")
                print(f"     - Subject: {profile.subject[:100] if profile.subject else 'N/A'}...")
                print(f"     - Summary: {profile.summary[:200] if profile.summary else 'N/A'}...")
                print(f"     - 时间戳: {profile.timestamp}")
        else:
            print(f"  ⚠️ Profile Memory 未提取")
        
        return profile_memories
    
    async def test_semantic_memory_extraction(self, episode_memory):
        """测试 Semantic Memory 提取耗时"""
        if not episode_memory:
            print("\n" + "="*80)
            print("⏭️  跳过: Semantic Memory 提取 (需要 Episode Memory)")
            print("="*80)
            return None
        
        print("\n" + "="*80)
        print("📊 测试 4: Semantic Memory 提取")
        print("="*80)
        print(f"  基于 Episode Memory: User {episode_memory.user_id}")
        
        semantic_memories = await self._measure_time(
            "Semantic Memory 提取",
            self.memory_manager.extract_memory(
                memcell_list=[],
                memory_type=MemoryType.SEMANTIC_SUMMARY,
                user_ids=[episode_memory.user_id],
                episode_memory=episode_memory,
            )
        )
        
        if semantic_memories:
            print(f"\n  ✅ Semantic Memory 提取成功")
            print(f"  提取数量: {len(semantic_memories)}")
            for idx, sem in enumerate(semantic_memories[:5], 1):
                print(f"\n  📝 Semantic {idx}:")
                # 尝试获取不同的属性
                if hasattr(sem, 'subject') and sem.subject:
                    print(f"     - Subject: {sem.subject[:100]}...")
                if hasattr(sem, 'predicate') and sem.predicate:
                    print(f"     - Predicate: {sem.predicate[:100]}...")
                if hasattr(sem, 'object') and sem.object:
                    print(f"     - Object: {sem.object[:100]}...")
                if hasattr(sem, 'content') and sem.content:
                    print(f"     - Content: {sem.content[:150]}...")
                if hasattr(sem, '__str__'):
                    print(f"     - 内容: {str(sem)[:150]}...")
        else:
            print(f"  ⚠️ Semantic Memory 未提取")
        
        return semantic_memories
    
    async def test_event_log_extraction(self, episode_memory):
        """测试 Event Log 提取耗时"""
        if not episode_memory:
            print("\n" + "="*80)
            print("⏭️  跳过: Event Log 提取 (需要 Episode Memory)")
            print("="*80)
            return None
        
        print("\n" + "="*80)
        print("📊 测试 5: Event Log 提取")
        print("="*80)
        print(f"  基于 Episode Memory: User {episode_memory.user_id}")
        
        event_log = await self._measure_time(
            "Event Log 提取",
            self.memory_manager.extract_memory(
                memcell_list=[],
                memory_type=MemoryType.EVENT_LOG,
                user_ids=[episode_memory.user_id],
                episode_memory=episode_memory,
            )
        )
        
        if event_log:
            print(f"\n  ✅ Event Log 提取成功")
            print(f"  Event Log 类型: {type(event_log).__name__}")
            
            # 打印 Event Log 详细信息
            if hasattr(event_log, 'events') and event_log.events:
                print(f"  事件数量: {len(event_log.events)}")
                for idx, event in enumerate(event_log.events[:3], 1):
                    print(f"\n  📝 Event {idx}:")
                    if hasattr(event, 'action'):
                        print(f"     - Action: {event.action}")
                    if hasattr(event, 'subject'):
                        print(f"     - Subject: {event.subject}")
                    if hasattr(event, 'object'):
                        print(f"     - Object: {event.object}")
                    if hasattr(event, 'timestamp'):
                        print(f"     - 时间戳: {event.timestamp}")
            elif hasattr(event_log, '__dict__'):
                # 尝试打印对象的属性
                attrs = {k: v for k, v in event_log.__dict__.items() if not k.startswith('_')}
                print(f"  属性: {list(attrs.keys())}")
        else:
            print(f"  ⚠️ Event Log 未提取")
        
        return event_log
    
    def print_summary(self):
        """打印性能测试总结"""
        print("\n" + "="*80)
        print("📈 性能测试总结")
        print("="*80)
        
        total_time = sum(r.duration_ms for r in self.results)
        successful_tests = [r for r in self.results if r.success]
        failed_tests = [r for r in self.results if not r.success]
        
        print(f"\n总测试数: {len(self.results)}")
        print(f"成功: {len(successful_tests)}")
        print(f"失败: {len(failed_tests)}")
        print(f"总耗时: {total_time:.2f} ms ({total_time/1000:.2f} 秒)")
        
        print("\n" + "-"*80)
        print("详细耗时统计:")
        print("-"*80)
        print(f"{'步骤':<45} {'耗时 (ms)':<15} {'占比':<10} {'状态':<10} {'详情'}")
        print("-"*80)
        
        for result in self.results:
            status = "✅ 成功" if result.success else "❌ 失败"
            percentage = (result.duration_ms / total_time) * 100 if total_time > 0 else 0
            print(f"{result.step_name:<45} {result.duration_ms:>12.2f} ms  {percentage:>6.2f}%  {status:<10} {result.details}")
        
        if successful_tests:
            print("\n" + "-"*80)
            print("各步骤耗时占比:")
            print("-"*80)
            for result in successful_tests:
                percentage = (result.duration_ms / total_time) * 100
                bar = "█" * int(percentage / 2)
                print(f"{result.step_name:<40} {percentage:>6.2f}% {bar}")
        
        print("\n" + "="*80)


async def main():
    """主函数"""
    print("="*80)
    print("🚀 记忆提取性能测试")
    print("="*80)
    print("\n本测试将测量各个记忆提取单元的耗时（分阶段测试）")
    print("包括: MemCell、Episode、Profile、Semantic、EventLog")
    print("\n💡 测试流程:")
    print("   1. 先单独测试 MemCell 提取（禁用下游记忆）")
    print("   2. 基于提取的 MemCell，单独测试各种下游记忆提取")
    print("   3. 这样可以准确测量每个阶段的耗时")
    print("\n开始测试...")
    
    tester = PerformanceTester()
    
    try:
        # 测试 MemCell 提取
        memcell = await tester.test_memcell_extraction()
        
        # 测试 Episode Memory 提取
        episode_memory = await tester.test_episode_memory_extraction(memcell)
        
        # 测试 Profile Memory 提取
        await tester.test_profile_memory_extraction(memcell)
        
        # 测试 Semantic Memory 提取
        await tester.test_semantic_memory_extraction(episode_memory)
        
        # 测试 Event Log 提取
        await tester.test_event_log_extraction(episode_memory)
        
    except Exception as e:
        print(f"\n❌ 测试过程中发生错误: {e}")
        import traceback
        traceback.print_exc()
    
    # 打印总结
    tester.print_summary()
    
    print("\n✅ 性能测试完成！")


if __name__ == "__main__":
    asyncio.run(main())

