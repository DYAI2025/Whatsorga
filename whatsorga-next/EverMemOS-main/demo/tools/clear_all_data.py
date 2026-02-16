"""清空所有记忆数据的工具函数

可以被其他测试脚本导入使用，也可以独立运行
"""
import asyncio
from infra_layer.adapters.out.persistence.document.memory.memcell import MemCell
from infra_layer.adapters.out.persistence.document.memory.episodic_memory import EpisodicMemory
from infra_layer.adapters.out.persistence.document.memory.personal_semantic_memory import PersonalSemanticMemory
from infra_layer.adapters.out.persistence.document.memory.personal_event_log import PersonalEventLog
from infra_layer.adapters.out.persistence.document.memory.conversation_status import ConversationStatus
from infra_layer.adapters.out.persistence.document.memory.cluster_state import ClusterState
from infra_layer.adapters.out.persistence.document.memory.user_profile import UserProfile
from infra_layer.adapters.out.search.milvus.memory.episodic_memory_collection import EpisodicMemoryCollection
from infra_layer.adapters.out.search.milvus.memory.semantic_memory_collection import SemanticMemoryCollection
from infra_layer.adapters.out.search.milvus.memory.event_log_collection import EventLogCollection
from core.di import get_bean_by_type
from component.redis_provider import RedisProvider


async def clear_all_memories(verbose: bool = True):
    """清空所有记忆数据（MongoDB、Milvus、Elasticsearch、Redis）
    
    Args:
        verbose: 是否显示详细信息
    """
    if verbose:
        print("\n🗑️  清空所有记忆数据...")
    
    try:
        # 1. 清空 MongoDB
        if verbose:
            print("   📦 清空 MongoDB...")
        
        memcell_count = await MemCell.find_all().count()
        episode_count = await EpisodicMemory.find_all().count()
        semantic_count = await PersonalSemanticMemory.find_all().count()
        eventlog_count = await PersonalEventLog.find_all().count()
        status_count = await ConversationStatus.find_all().count()
        cluster_count = await ClusterState.find_all().count()
        profile_count = await UserProfile.find_all().count()
        
        await MemCell.find_all().delete()
        await EpisodicMemory.find_all().delete()
        await PersonalSemanticMemory.find_all().delete()
        await PersonalEventLog.find_all().delete()
        await ConversationStatus.find_all().delete()
        await ClusterState.find_all().delete()
        await UserProfile.find_all().delete()
        
        if verbose:
            print(f"      ✅ MemCell: {memcell_count} 条")
            print(f"      ✅ EpisodicMemory: {episode_count} 条")
            print(f"      ✅ PersonalSemanticMemory: {semantic_count} 条")
            print(f"      ✅ PersonalEventLog: {eventlog_count} 条")
            print(f"      ✅ ConversationStatus: {status_count} 条")
            print(f"      ✅ ClusterState: {cluster_count} 条")
            print(f"      ✅ UserProfile: {profile_count} 条")
        
        # 2. 清空 Milvus（三个独立的 Collection）
        if verbose:
            print("   🔍 清空 Milvus...")
        
        # 使用drop并重新创建Collection的方式清空（保留alias）
        collections_to_clear = [
            ("episodic_memory", EpisodicMemoryCollection()),
            ("semantic_memory", SemanticMemoryCollection()),
            ("event_log", EventLogCollection()),
        ]
        
        for coll_name, milvus_collection in collections_to_clear:
            try:
                from pymilvus import utility, Collection
                alias_name = milvus_collection._alias_name
                
                # 检查alias是否存在
                if utility.has_collection(alias_name, using=milvus_collection._using):
                    # 获取当前alias指向的真实Collection名称
                    try:
                        from pymilvus import connections
                        conn = connections._fetch_handler(milvus_collection._using)
                        desc = conn.describe_alias(alias_name)
                        old_real_name = desc.get("collection_name") if isinstance(desc, dict) else None
                    except Exception:
                        old_real_name = None
                    
                    if old_real_name:
                        # 1. 先创建新的Collection
                        new_coll = milvus_collection.create_new_collection()
                        if verbose:
                            print(f"      ✅ {coll_name}: 创建新Collection: {new_coll.name}")
                        
                        # 2. 切换alias到新Collection
                        milvus_collection.switch_alias(new_coll, drop_old=True)
                        if verbose:
                            print(f"      ✅ {coll_name}: 已切换alias '{alias_name}' 到新Collection并删除旧Collection '{old_real_name}'")
                    else:
                        if verbose:
                            print(f"      ⚠️  {coll_name}: 无法获取旧Collection名称")
                else:
                    if verbose:
                        print(f"      ✅ {coll_name}: Collection不存在，跳过清空")
            except Exception as e:
                if verbose:
                    print(f"      ⚠️  {coll_name} 清空跳过: {e}")
        
        # 3. 清空 Elasticsearch
        if verbose:
            print("   🔎 清空 Elasticsearch...")
        
        try:
            from component.elasticsearch_client_factory import ElasticsearchClientFactory
            from infra_layer.adapters.out.search.elasticsearch.memory.episodic_memory import EpisodicMemoryDoc
            
            # 获取ES客户端连接
            es_factory = get_bean_by_type(ElasticsearchClientFactory)
            es_client_wrapper = await es_factory.get_default_client()
            es_client = es_client_wrapper.async_client
            
            # 获取实际的 alias 名称（带后缀）
            alias_name = EpisodicMemoryDoc._index._name
            
            # 获取alias指向的所有索引
            alias_info = await es_client.indices.get_alias(name=alias_name)
            
            total_deleted = 0
            # 删除每个索引中的所有文档
            for index_name in alias_info.keys():
                # 持续删除直到没有更多文档
                while True:
                    response = await es_client.delete_by_query(
                        index=index_name,
                        body={"query": {"match_all": {}}},
                        conflicts="proceed",  # 忽略版本冲突
                        refresh=True,  # 立即刷新索引
                        scroll_size=5000,  # 每批处理5000条
                        wait_for_completion=True  # 等待完成
                    )
                    deleted_count = response.get('deleted', 0) if isinstance(response, dict) else 0
                    total_deleted += deleted_count
                    
                    if verbose and deleted_count > 0:
                        print(f"      - 清空索引 {index_name}: 本轮删除 {deleted_count} 条文档")
                    
                    # 如果没有删除任何文档，说明已经清空
                    if deleted_count == 0:
                        break
            
            if verbose:
                print(f"      ✅ Elasticsearch 已清空（总计删除 {total_deleted} 条文档）")
        except Exception as e:
            if verbose:
                print(f"      ⚠️  Elasticsearch 清空跳过: {e}")
        
        # 4. 清空 Redis
        if verbose:
            print("   💾 清空 Redis...")
        
        redis_provider = get_bean_by_type(RedisProvider)
        keys = await redis_provider.keys("chat_history:*")
        if keys:
            for key in keys:
                await redis_provider.delete(key)
            if verbose:
                print(f"      ✅ Redis 已清空 {len(keys)} 个 chat_history key")
        else:
            if verbose:
                print(f"      ✅ Redis 没有 chat_history 数据")
        
        if verbose:
            print("✅ 所有记忆数据已清空！\n")
        
        # 验证清空结果
        if verbose:
            print("🔍 验证清空结果...")
            
            # 1. 验证 MongoDB
            remaining_memcell = await MemCell.find_all().count()
            remaining_episode = await EpisodicMemory.find_all().count()
            remaining_semantic = await PersonalSemanticMemory.find_all().count()
            remaining_eventlog = await PersonalEventLog.find_all().count()
            remaining_status = await ConversationStatus.find_all().count()
            remaining_cluster = await ClusterState.find_all().count()
            remaining_profile = await UserProfile.find_all().count()
            
            mongodb_total = (remaining_memcell + remaining_episode + remaining_semantic + 
                           remaining_eventlog + remaining_status + remaining_cluster + remaining_profile)
            
            if mongodb_total == 0:
                print(f"   ✅ MongoDB: 0 条记录")
            else:
                print(f"   ⚠️  MongoDB 仍有 {mongodb_total} 条记录:")
                if remaining_memcell > 0:
                    print(f"      - MemCell: {remaining_memcell} 条")
                if remaining_episode > 0:
                    print(f"      - EpisodicMemory: {remaining_episode} 条")
                if remaining_semantic > 0:
                    print(f"      - PersonalSemanticMemory: {remaining_semantic} 条")
                if remaining_eventlog > 0:
                    print(f"      - PersonalEventLog: {remaining_eventlog} 条")
                if remaining_status > 0:
                    print(f"      - ConversationStatus: {remaining_status} 条")
                if remaining_cluster > 0:
                    print(f"      - ClusterState: {remaining_cluster} 条")
                if remaining_profile > 0:
                    print(f"      - UserProfile: {remaining_profile} 条")
            
            # 2. 验证 Milvus (检查3个Collection中的数据量)
            try:
                from pymilvus import utility
                
                collections_to_verify = [
                    ("episodic_memory", EpisodicMemoryCollection()),
                    ("semantic_memory", SemanticMemoryCollection()),
                    ("event_log", EventLogCollection()),
                ]
                
                total_milvus_count = 0
                for coll_name, milvus_collection in collections_to_verify:
                    try:
                        alias_name = milvus_collection._alias_name
                        
                        # 检查alias是否存在
                        if utility.has_collection(alias_name):
                            # Collection存在，查询数量
                            milvus_collection.ensure_collection_desc()
                            collection = milvus_collection.async_collection()
                            count = collection.num_entities
                            total_milvus_count += count
                            if count > 0:
                                print(f"   ⚠️  Milvus {coll_name} 仍有 {count} 条向量")
                    except Exception as e:
                        if "can't find collection" not in str(e):
                            print(f"   ⚠️  Milvus {coll_name} 验证跳过: {e}")
                
                if total_milvus_count == 0:
                    print(f"   ✅ Milvus: 0 条向量")
            except Exception as e:
                print(f"   ⚠️  Milvus 验证跳过: {e}")
            
            # 3. 验证 Elasticsearch
            try:
                from component.elasticsearch_client_factory import ElasticsearchClientFactory
                from infra_layer.adapters.out.search.elasticsearch.memory.episodic_memory import EpisodicMemoryDoc
                
                # 获取ES客户端连接
                es_factory = get_bean_by_type(ElasticsearchClientFactory)
                es_client_wrapper = await es_factory.get_default_client()
                es_client = es_client_wrapper.async_client
                
                # 获取实际的 alias 名称（带后缀）
                actual_alias = EpisodicMemoryDoc._index._name
                
                # 直接使用async_client的count API
                response = await es_client.count(index=actual_alias)
                es_count = response.get('count', 0) if isinstance(response, dict) else response.get('count', 0) if hasattr(response, 'get') else 0
                
                if es_count == 0:
                    print(f"   ✅ Elasticsearch: 0 条文档")
                else:
                    print(f"   ⚠️  Elasticsearch 仍有 {es_count} 条文档")
            except Exception as e:
                print(f"   ⚠️  Elasticsearch 验证跳过: {e}")
            
            # 4. 验证 Redis
            redis_provider = get_bean_by_type(RedisProvider)
            remaining_keys = await redis_provider.keys("chat_history:*")
            if not remaining_keys:
                print(f"   ✅ Redis: 0 个 chat_history key")
            else:
                print(f"   ⚠️  Redis 仍有 {len(remaining_keys)} 个 chat_history key:")
                for key in remaining_keys[:5]:  # 最多显示5个
                    print(f"      - {key}")
                if len(remaining_keys) > 5:
                    print(f"      ... 还有 {len(remaining_keys) - 5} 个")
            
            print()
        
        return {
            "mongodb": {
                "memcell": memcell_count,
                "episode": episode_count,
                "semantic": semantic_count,
                "eventlog": eventlog_count,
                "status": status_count,
                "cluster": cluster_count,
                "profile": profile_count,
            },
            "redis_keys": len(keys) if keys else 0,
        }
        
    except Exception as e:
        print(f"❌ 清空数据时出错: {e}")
        import traceback
        traceback.print_exc()
        raise


async def main():
    """独立运行时的入口函数"""
    print("=" * 100)
    print("🗑️  清空所有记忆数据工具")
    print("=" * 100)
    
    result = await clear_all_memories(verbose=True)
    
    print("\n📊 清空统计:")
    print(f"   MongoDB 总计: {sum(result['mongodb'].values())} 条")
    print(f"   Redis Keys: {result['redis_keys']} 个")
    print("=" * 100)


if __name__ == "__main__":
    asyncio.run(main())

