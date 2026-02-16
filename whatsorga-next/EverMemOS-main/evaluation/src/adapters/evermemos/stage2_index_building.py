import json
import os
import sys
import pickle
from pathlib import Path

import nltk
from nltk.corpus import stopwords
from nltk.stem import PorterStemmer
from nltk.tokenize import word_tokenize
from rank_bm25 import BM25Okapi
import asyncio




from evaluation.src.adapters.evermemos.config import ExperimentConfig
from agentic_layer import vectorize_service


def ensure_nltk_data():
    """Ensure required NLTK data is downloaded."""
    try:
        nltk.data.find("tokenizers/punkt")
    except LookupError:
        print("Downloading punkt...")
        nltk.download("punkt", quiet=True)
    
    try:
        nltk.data.find("tokenizers/punkt_tab")
    except LookupError:
        print("Downloading punkt_tab...")
        nltk.download("punkt_tab", quiet=True)

    try:
        nltk.data.find("corpora/stopwords")
    except LookupError:
        print("Downloading stopwords...")
        nltk.download("stopwords", quiet=True)
    
    # 🔥 验证 stopwords 是否可用
    try:
        from nltk.corpus import stopwords
        test_stopwords = stopwords.words("english")
        if not test_stopwords:
            raise ValueError("Stopwords is empty")
    except Exception as e:
        print(f"Warning: NLTK stopwords error: {e}")
        print("Re-downloading stopwords...")
        nltk.download("stopwords", quiet=False, force=True)


def build_searchable_text(doc: dict) -> str:
    """
    Build searchable text from a document with weighted fields.

    Priority:
    1. If event_log exists, use atomic_fact for indexing
    2. Otherwise, fall back to original fields:
       - "subject" corresponds to "title" (weight * 3)
       - "summary" corresponds to "summary" (weight * 2)
       - "episode" corresponds to "content" (weight * 1)
    """
    parts = []

    # 优先使用event_log的atomic_fact（如果存在）
    if doc.get("event_log") and doc["event_log"].get("atomic_fact"):
        atomic_facts = doc["event_log"]["atomic_fact"]
        if isinstance(atomic_facts, list):
            # 🔥 修复：处理嵌套的 atomic_fact 结构
            # atomic_fact 可能是字符串列表或字典列表（包含 "fact" 和 "embedding"）
            for fact in atomic_facts:
                if isinstance(fact, dict) and "fact" in fact:
                    # 新格式：{"fact": "...", "embedding": [...]}
                    parts.append(fact["fact"])
                elif isinstance(fact, str):
                    # 旧格式：纯字符串列表（向后兼容）
                    parts.append(fact)
            return " ".join(str(fact) for fact in parts if fact)

    # 回退到原有字段（保持向后兼容）
    # Title has highest weight (repeat 3 times)
    if doc.get("subject"):
        parts.extend([doc["subject"]] * 3)

    # Summary (repeat 2 times)
    if doc.get("summary"):
        parts.extend([doc["summary"]] * 2)

    # Content
    if doc.get("episode"):
        parts.append(doc["episode"])

    return " ".join(str(part) for part in parts if part)


def tokenize(text: str, stemmer, stop_words: set) -> list[str]:
    """
    NLTK-based tokenization with stemming and stopword removal.
    """
    if not text:
        return []

    tokens = word_tokenize(text.lower())

    processed_tokens = [
        stemmer.stem(token)
        for token in tokens
        if token.isalpha() and len(token) >= 2 and token not in stop_words
    ]

    return processed_tokens


def build_bm25_index(
    config: ExperimentConfig, data_dir: Path, bm25_save_dir: Path
) -> list[list[float]]:
    # --- NLTK Setup ---
    print("Ensuring NLTK data is available...")
    ensure_nltk_data()
    stemmer = PorterStemmer()
    stop_words = set(stopwords.words("english"))

    # --- Data Loading and Processing ---
    # corpus = [] # This line is removed as per the new_code
    # original_docs = [] # This line is removed as per the new_code

    print(f"Reading data from: {data_dir}")

    for i in range(config.num_conv):
        file_path = data_dir / f"memcell_list_conv_{i}.json"
        if not file_path.exists():
            print(f"Warning: File not found, skipping: {file_path}")
            continue

        print(f"\nProcessing {file_path.name}...")

        corpus = []
        original_docs = []

        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)

            for doc in data:
                original_docs.append(doc)
                searchable_text = build_searchable_text(doc)
                tokenized_text = tokenize(searchable_text, stemmer, stop_words)
                corpus.append(tokenized_text)

        if not corpus:
            print(
                f"Warning: No documents found in {file_path.name}. Skipping index creation."
            )
            continue

        print(f"Processed {len(original_docs)} documents from {file_path.name}.")

        # --- BM25 Indexing ---
        print(f"Building BM25 index for {file_path.name}...")
        bm25 = BM25Okapi(corpus)

        # --- Saving the Index ---
        index_data = {"bm25": bm25, "docs": original_docs}

        output_path = bm25_save_dir / f"bm25_index_conv_{i}.pkl"
        print(f"Saving index to: {output_path}")
        with open(output_path, "wb") as f:
            pickle.dump(index_data, f)


async def build_emb_index(config: ExperimentConfig, data_dir: Path, emb_save_dir: Path):
    """
    构建 Embedding 索引（稳定版）
    
    性能优化策略：
    1. 受控并发：严格遵守 API Semaphore(5) 限制
    2. 保守批次大小：256 个文本/批次（避免超时）
    3. 串行批次提交：分组提交，避免队列堆积
    4. 进度监控：实时显示处理进度和速度
    
    优化效果：
    - 稳定性优先，避免超时和 API 过载
    - API 并发数：5（受 vectorize_service.Semaphore 控制）
    - 批次大小：256（平衡稳定性和效率）
    """
    # 🔥 优化1：保守的批次大小（避免超时）
    BATCH_SIZE = 256  # 使用较大批次（单次 API 调用处理更多，减少请求数）
    MAX_CONCURRENT_BATCHES = 5  # 🔥 严格控制并发数（与 Semaphore(5) 匹配）
    
    import time  # 用于性能统计
    
    for i in range(config.num_conv):
        file_path = data_dir / f"memcell_list_conv_{i}.json"
        if not file_path.exists():
            print(f"Warning: File not found, skipping: {file_path}")
            continue

        print(f"\n{'='*60}")
        print(f"Processing {file_path.name} for embedding...")
        print(f"{'='*60}")

        with open(file_path, "r", encoding="utf-8") as f:
            original_docs = json.load(f)

        texts_to_embed = []
        doc_field_map = []
        for doc_idx, doc in enumerate(original_docs):
            # 优先使用event_log（如果存在）
            if doc.get("event_log") and doc["event_log"].get("atomic_fact"):
                atomic_facts = doc["event_log"]["atomic_fact"]
                if isinstance(atomic_facts, list) and atomic_facts:
                    # 🔥 关键改动：每个atomic_fact单独计算embedding（MaxSim策略）
                    # 这样可以精确匹配到某个具体的原子事实，避免语义稀释
                    for fact_idx, fact in enumerate(atomic_facts):
                        # 🔥 修复：兼容两种格式（字符串 / 字典）
                        fact_text = None
                        if isinstance(fact, dict) and "fact" in fact:
                            # 新格式：{"fact": "...", "embedding": [...]}
                            fact_text = fact["fact"]
                        elif isinstance(fact, str):
                            # 旧格式：纯字符串
                            fact_text = fact
                        
                        # 确保fact非空
                        if fact_text and fact_text.strip():
                            texts_to_embed.append(fact_text)
                            doc_field_map.append((doc_idx, f"atomic_fact_{fact_idx}"))
                    continue

            # 回退到原有字段（保持向后兼容）
            for field in ["subject", "summary", "episode"]:
                if text := doc.get(field):
                    texts_to_embed.append(text)
                    doc_field_map.append((doc_idx, field))

        if not texts_to_embed:
            print(
                f"Warning: No documents found in {file_path.name}. Skipping embedding creation."
            )
            continue

        total_texts = len(texts_to_embed)
        total_batches = (total_texts + BATCH_SIZE - 1) // BATCH_SIZE
        print(f"Total texts to embed: {total_texts}")
        print(f"Batch size: {BATCH_SIZE}")
        print(f"Total batches: {total_batches}")
        print(f"Max concurrent batches: {MAX_CONCURRENT_BATCHES}")
        print(f"\nStarting parallel embedding generation...")
        
        # 🔥 优化2：稳定的批次处理（避免超时）
        start_time = time.time()
        
        async def process_batch_with_retry(batch_idx: int, batch_texts: list, max_retries: int = 3) -> tuple[int, list]:
            """处理单个批次（异步 + 重试）"""
            for attempt in range(max_retries):
                try:
                    # 调用 API 获取 embeddings（受 Semaphore(5) 控制并发数）
                    batch_embeddings = await vectorize_service.get_text_embeddings(batch_texts)
                    return (batch_idx, batch_embeddings)
                except Exception as e:
                    if attempt < max_retries - 1:
                        wait_time = 2.0 * (2 ** attempt)  # 指数退避：2s, 4s
                        print(f"  ⚠️  Batch {batch_idx + 1}/{total_batches} failed (attempt {attempt + 1}), retrying in {wait_time:.1f}s: {e}")
                        await asyncio.sleep(wait_time)
                    else:
                        print(f"  ❌ Batch {batch_idx + 1}/{total_batches} failed after {max_retries} attempts: {e}")
                        return (batch_idx, [])
        
        # 🔥 优化3：分组串行提交（避免队列堆积导致超时）
        print(f"Processing {total_batches} batches in groups of {MAX_CONCURRENT_BATCHES}...")
        
        batch_results = []
        completed = 0
        
        # 🔥 关键：分组提交，每组最多 MAX_CONCURRENT_BATCHES 个并发
        for group_start in range(0, total_texts, BATCH_SIZE * MAX_CONCURRENT_BATCHES):
            # 计算当前组的批次范围
            group_end = min(group_start + BATCH_SIZE * MAX_CONCURRENT_BATCHES, total_texts)
            group_tasks = []
            
            for j in range(group_start, group_end, BATCH_SIZE):
                batch_idx = j // BATCH_SIZE
                batch_texts = texts_to_embed[j : j + BATCH_SIZE]
                task = process_batch_with_retry(batch_idx, batch_texts)
                group_tasks.append(task)
            
            # 🔥 并发处理当前组（最多 MAX_CONCURRENT_BATCHES 个）
            print(f"  Group {group_start//BATCH_SIZE//MAX_CONCURRENT_BATCHES + 1}: Processing {len(group_tasks)} batches concurrently...")
            group_results = await asyncio.gather(*group_tasks, return_exceptions=False)
            batch_results.extend(group_results)
            
            completed += len(group_tasks)
            progress = (completed / total_batches) * 100
            print(f"  Progress: {completed}/{total_batches} batches ({progress:.1f}%)")
            
            # 🔥 组间延迟（给 API 服务器喘息时间）
            if group_end < total_texts:
                await asyncio.sleep(1.0)  # 1秒组间延迟
        
        # 按批次顺序重组结果
        all_embeddings = []
        for batch_idx, batch_embeddings in sorted(batch_results, key=lambda x: x[0]):
            all_embeddings.extend(batch_embeddings)
        
        elapsed_time = time.time() - start_time
        speed = total_texts / elapsed_time if elapsed_time > 0 else 0
        print(f"\n✅ Embedding generation complete!")
        print(f"   - Total texts: {total_texts}")
        print(f"   - Total embeddings: {len(all_embeddings)}")
        print(f"   - Time elapsed: {elapsed_time:.2f}s")
        print(f"   - Speed: {speed:.1f} texts/sec")
        print(f"   - Average batch time: {elapsed_time/total_batches:.2f}s")
        
        # 验证结果完整性
        if len(all_embeddings) != total_texts:
            print(f"   ⚠️  Warning: Expected {total_texts} embeddings, got {len(all_embeddings)}")
        else:
            print(f"   ✓ All embeddings generated successfully")

        # Re-associate embeddings with their original documents and fields
        # 🔥 改进：支持每个文档有多个atomic_fact embeddings（用于MaxSim策略）
        doc_embeddings = [{"doc": doc, "embeddings": {}} for doc in original_docs]
        
        for (doc_idx, field), emb in zip(doc_field_map, all_embeddings):
            # 如果是atomic_fact字段，保存为列表（支持多个atomic_fact）
            if field.startswith("atomic_fact_"):
                if "atomic_facts" not in doc_embeddings[doc_idx]["embeddings"]:
                    doc_embeddings[doc_idx]["embeddings"]["atomic_facts"] = []
                doc_embeddings[doc_idx]["embeddings"]["atomic_facts"].append(emb)
            else:
                # 其他字段直接保存
                doc_embeddings[doc_idx]["embeddings"][field] = emb

        # The final structure of the saved .pkl file will be a list of dicts:
        # [
        #     {
        #         "doc": { ... original document ... },
        #         "embeddings": {
        #             "atomic_facts": [  # 🔥 新增：atomic_fact embeddings列表（用于MaxSim）
        #                 [ ... embedding vector for fact 0 ... ],
        #                 [ ... embedding vector for fact 1 ... ],
        #                 ...
        #             ],
        #             "subject": [ ... embedding vector ... ],  # 向后兼容的传统字段
        #             "summary": [ ... embedding vector ... ],
        #             "episode": [ ... embedding vector ... ]
        #         }
        #     },
        #     ...
        # ]
        output_path = emb_save_dir / f"embedding_index_conv_{i}.pkl"
        emb_save_dir.mkdir(parents=True, exist_ok=True)
        print(f"Saving embeddings to: {output_path}")
        with open(output_path, "wb") as f:
            pickle.dump(doc_embeddings, f)


async def main():
    """Main function to build and save the BM25 index."""
    # --- Configuration ---
    # The directory containing the JSON files
    config = ExperimentConfig()
    # 🔥 修正：实际文件在 locomo_evaluation/ 目录下，而不是 results/ 目录
    data_dir = Path(__file__).parent / config.experiment_name / "memcells"
    bm25_save_dir = (
        Path(__file__).parent / config.experiment_name / "bm25_index"
    )
    emb_save_dir = (
        Path(__file__).parent / config.experiment_name / "vectors"
    )
    os.makedirs(bm25_save_dir, exist_ok=True)
    os.makedirs(emb_save_dir, exist_ok=True)
    build_bm25_index(config, data_dir, bm25_save_dir)
    if config.use_emb:
        await build_emb_index(config, data_dir, emb_save_dir)
    # data_dir = Path("/Users/admin/Documents/Projects/b001-memsys/evaluation/locomo_evaluation/results/locomo_evaluation_0/")

    # Where to save the final index file
    # output_path = data_dir / "bm25_index.pkl" # This line is removed as per the new_code

    print("\nAll indexing complete!")


if __name__ == "__main__":
    asyncio.run(main())
