"""API JSON → models dataclass 适配器

将 XHS REST API 响应 JSON 转换为 redclaw.xhs.models 中现有的 dataclass 类型。
这样所有下游代码 (工具处理程序、存储、OCR 流程) 无需改动。
"""

from typing import Dict, List, Optional

from .models import (
    Comment,
    CommentList,
    Cover,
    DetailImageInfo,
    Feed,
    FeedDetail,
    FeedDetailResponse,
    ImageInfo,
    InteractInfo,
    NoteCard,
    User,
)


def _get(d: dict, *keys: str, default=None):
    """Try multiple key formats (snake_case, camelCase)"""
    for k in keys:
        if k in d:
            return d[k]
    return default


def adapt_search_items(items: List[Dict]) -> List[Feed]:
    """API 搜索响应 items → Feed 列表

    API 返回 snake_case (note_card, display_title, xsec_token...)
    兼容 camelCase (noteCard, displayTitle, xsecToken...)
    """
    feeds = []
    for item in items:
        nc = item.get("note_card") or item.get("noteCard") or {}

        feeds.append(Feed(
            xsec_token=_get(item, "xsec_token", "xsecToken", default=""),
            id=_get(item, "id", default=""),
            model_type=_get(item, "model_type", "modelType", default=""),
            note_card=NoteCard(
                type=_get(nc, "type", default=""),
                display_title=_get(nc, "display_title", "displayTitle", default=""),
                user=User(
                    user_id=_get(nc.get("user", {}), "user_id", "userId", default=""),
                    nickname=_get(nc.get("user", {}), "nickname", default=""),
                    nick_name=_get(nc.get("user", {}), "nick_name", "nickName", default=""),
                    avatar=_get(nc.get("user", {}), "avatar", default=""),
                ),
                interact_info=InteractInfo(
                    liked=_get(nc.get("interact_info", nc.get("interactInfo", {})), "liked", default=False),
                    liked_count=str(_get(nc.get("interact_info", nc.get("interactInfo", {})), "liked_count", "likedCount", default="0")),
                    shared_count=str(_get(nc.get("interact_info", nc.get("interactInfo", {})), "shared_count", "sharedCount", default="0")),
                    comment_count=str(_get(nc.get("interact_info", nc.get("interactInfo", {})), "comment_count", "commentCount", default="0")),
                    collected_count=str(_get(nc.get("interact_info", nc.get("interactInfo", {})), "collected_count", "collectedCount", default="0")),
                    collected=_get(nc.get("interact_info", nc.get("interactInfo", {})), "collected", default=False),
                ),
                cover=Cover(
                    width=_get(nc.get("cover", {}), "width", default=0),
                    height=_get(nc.get("cover", {}), "height", default=0),
                    url=_get(nc.get("cover", {}), "url", default=""),
                    file_id=_get(nc.get("cover", {}), "file_id", "fileId", default=""),
                    url_pre=_get(nc.get("cover", {}), "url_pre", "urlPre", default=""),
                    url_default=_get(nc.get("cover", {}), "url_default", "urlDefault", default=""),
                ),
            ),
            index=_get(item, "index", default=0),
        ))
    return feeds


def adapt_feed_detail(note_card: Dict, note_id: str = "", xsec_token: str = "") -> FeedDetail:
    """API feed 详情响应 note_card → FeedDetail"""
    image_list = []
    for img in (note_card.get("image_list") or note_card.get("imageList") or []):
        image_list.append(DetailImageInfo(
            width=_get(img, "width", default=0),
            height=_get(img, "height", default=0),
            url_default=_get(img, "url_default", "urlDefault", default=""),
            url_pre=_get(img, "url_pre", "urlPre", default=""),
            live_photo=_get(img, "live_photo", "livePhoto", default=False),
        ))

    interact_data = note_card.get("interact_info") or note_card.get("interactInfo") or {}
    return FeedDetail(
        note_id=_get(note_card, "note_id", "noteId", default=note_id),
        xsec_token=_get(note_card, "xsec_token", "xsecToken", default=xsec_token),
        title=_get(note_card, "title", default=""),
        desc=_get(note_card, "desc", default=""),
        type=_get(note_card, "type", default=""),
        time=_get(note_card, "time", default=0),
        ip_location=_get(note_card, "ip_location", "ipLocation", default=""),
        user=User(
            user_id=_get(note_card.get("user", {}), "user_id", "userId", default=""),
            nickname=_get(note_card.get("user", {}), "nickname", default=""),
            nick_name=_get(note_card.get("user", {}), "nick_name", "nickName", default=""),
            avatar=_get(note_card.get("user", {}), "avatar", default=""),
        ),
        interact_info=InteractInfo(
            liked=_get(interact_data, "liked", default=False),
            liked_count=str(_get(interact_data, "liked_count", "likedCount", default="0")),
            shared_count=str(_get(interact_data, "shared_count", "sharedCount", default="0")),
            comment_count=str(_get(interact_data, "comment_count", "commentCount", default="0")),
            collected_count=str(_get(interact_data, "collected_count", "collectedCount", default="0")),
            collected=_get(interact_data, "collected", default=False),
        ),
        image_list=image_list,
    )


def adapt_comment(comment_data: Dict) -> Comment:
    """API 评论数据 → Comment"""
    return Comment(
        id=_get(comment_data, "id", default=""),
        note_id=_get(comment_data, "note_id", "noteId", default=""),
        content=_get(comment_data, "content", default=""),
        like_count=str(_get(comment_data, "like_count", "likeCount", default="0")),
        create_time=_get(comment_data, "create_time", "createTime", default=0),
        ip_location=_get(comment_data, "ip_location", "ipLocation", default=""),
        liked=_get(comment_data, "liked", default=False),
        user_info=User(
            user_id=_get(comment_data.get("user_info") or comment_data.get("userInfo") or {}, "user_id", "userId", default=""),
            nickname=_get(comment_data.get("user_info") or comment_data.get("userInfo") or {}, "nickname", default=""),
            nick_name=_get(comment_data.get("user_info") or comment_data.get("userInfo") or {}, "nick_name", "nickName", default=""),
            avatar=_get(comment_data.get("user_info") or comment_data.get("userInfo") or {}, "avatar", default=""),
        ),
        sub_comment_count=str(_get(comment_data, "sub_comment_count", "subCommentCount", default="0")),
        sub_comments=[adapt_comment(c) for c in (
            comment_data.get("sub_comments") or comment_data.get("subComments") or []
        )],
        show_tags=comment_data.get("show_tags") or comment_data.get("showTags") or [],
    )


def adapt_comments(comments_data: Dict) -> CommentList:
    """API 评论响应 → CommentList"""
    comments = [adapt_comment(c) for c in comments_data.get("comments", []) or []]
    return CommentList(
        list_=comments,
        cursor=_get(comments_data, "cursor", default=""),
        has_more=_get(comments_data, "has_more", "hasMore", default=False),
    )


def adapt_feed_detail_response(note_card: Dict, note_id: str = "",
                               xsec_token: str = "",
                               comments_data: Optional[Dict] = None) -> FeedDetailResponse:
    """API 响应 → FeedDetailResponse (笔记 + 评论)"""
    feed_detail = adapt_feed_detail(note_card, note_id, xsec_token)
    if comments_data:
        comment_list = adapt_comments(comments_data)
    else:
        comment_list = CommentList()
    return FeedDetailResponse(note=feed_detail, comments=comment_list)
