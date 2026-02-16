"""
数据格式转换模块

将外部数据格式转换为 memory_layer 所需的 RawData 格式
"""

from typing import Dict, Any, Optional
from memory_layer.memcell_extractor.base_memcell_extractor import RawData
from common_utils.datetime_utils import from_iso_format
from zoneinfo import ZoneInfo
from core.observation.logger import get_logger

logger = get_logger(__name__)

# 注意：group_name 现在完全依赖外部传入，不再从数据库查询
# ChatGroupRawRepository 已被移除


async def convert_single_message_to_raw_data(
    input_data: Dict[str, Any],
    data_id_field: str = "_id",
    group_name: Optional[str] = None,
) -> RawData:
    """
    将输入数据转换为 RawData 格式

    Args:
        input_data: 包含 _id, fullName, receiverId, roomId, userIdList,
                   referList, content, createTime, createBy, updateTime, orgId 的字典
        data_id_field: 用作 data_id 的字段名，默认为 "_id"
        group_name: 群组名称（从外部传入，会添加到消息的 content 中）

    Returns:
        RawData 对象
    """
    # 提取 data_id
    data_id = str(input_data.get(data_id_field, ""))

    room_id = input_data.get("roomId")

    # group_name 完全依赖外部传入
    # 如果外部没有传入，则为 None（不再查询数据库）
    if group_name:
        logger.debug("使用外部传入的 group_name: %s", group_name)
    else:
        logger.debug("未从外部传入 group_name，将使用 None")

    # 构建 content 字典，包含所有业务相关字段
    content = {
        "speaker_name": input_data.get("fullName"),
        "receiverId": input_data.get("receiverId"),
        "roomId": room_id,
        "groupName": group_name,  # 添加群组名称
        "userIdList": input_data.get("userIdList", []),
        "referList": input_data.get("referList", []),
        "content": input_data.get("content"),
        "timestamp": from_iso_format(
            input_data.get("createTime"), ZoneInfo("UTC")
        ),  # 使用转换后的UTC时间
        "createBy": input_data.get("createBy"),
        "updateTime": from_iso_format(
            input_data.get("updateTime"), ZoneInfo("UTC")
        ),  # 使用转换后的UTC时间
        "orgId": input_data.get("orgId"),
        "speaker_id": input_data.get("createBy"),
        "msgType": input_data.get("msgType"),
        "data_id": data_id,
    }

    # 如果input_data中包含这些字段，则添加到content中
    if "readStatus" in input_data:
        content["readStatus"] = input_data.get("readStatus")
    if "notifyType" in input_data:
        content["notifyType"] = input_data.get("notifyType")
    if "isReplySuggest" in input_data:
        content["isReplySuggest"] = input_data.get("isReplySuggest")
    if "readUpdateTime" in input_data:
        content["readUpdateTime"] = from_iso_format(
            input_data.get("readUpdateTime"), ZoneInfo("UTC")
        )

    # 构建 metadata，包含系统字段
    metadata = {
        "original_id": data_id,
        "createTime": from_iso_format(
            input_data.get("createTime"), ZoneInfo("UTC")
        ),  # 使用转换后的UTC时间
        "updateTime": from_iso_format(
            input_data.get("updateTime"), ZoneInfo("UTC")
        ),  # 使用转换后的UTC时间
        "createBy": input_data.get("createBy"),
        "orgId": input_data.get("orgId"),
    }

    return RawData(content=content, data_id=data_id, metadata=metadata)


async def convert_conversation_to_raw_data_list(
    input_data_list: list[Dict[str, Any]],
    data_id_field: str = "_id",
    group_name: Optional[str] = None,
) -> list[RawData]:
    """
    批量转换数据为 RawData 格式

    Args:
        input_data_list: 输入数据列表
        data_id_field: 用作 data_id 的字段名，默认为 "_id"
        group_name: 群组名称（从外部传入，会传递给每条消息转换）

    Returns:
        RawData 对象列表
    """
    return [
        await convert_single_message_to_raw_data(
            data, data_id_field=data_id_field, group_name=group_name
        )
        for data in input_data_list
    ]
