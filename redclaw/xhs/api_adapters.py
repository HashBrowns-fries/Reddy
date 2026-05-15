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


def adapt_search_items(items: List[Dict]) -> List[Feed]:
    """API 搜索响应 items → Feed 列表

    API 搜索响应的 items 结构与 __INITIAL_STATE__ 中的 Feed 结构非常相似:
      item.id → Feed.id
      item.modelType → Feed.model_type
      item.xsecToken → Feed.xsec_token
      item.noteCard → Feed.note_card
    """
    feeds = []
    for item in items:
        note_card_data = item.get("noteCard", {})

        feeds.append(Feed(
            xsec_token=item.get("xsecToken", ""),
            id=item.get("id", ""),
            model_type=item.get("modelType", ""),
            note_card=NoteCard(
                type=note_card_data.get("type", ""),
                display_title=note_card_data.get("displayTitle", ""),
                user=User(
                    user_id=note_card_data.get("user", {}).get("userId", ""),
                    nickname=note_card_data.get("user", {}).get("nickname", ""),
                    nick_name=note_card_data.get("user", {}).get("nickName", ""),
                    avatar=note_card_data.get("user", {}).get("avatar", ""),
                ),
                interact_info=InteractInfo(
                    liked=note_card_data.get("interactInfo", {}).get("liked", False),
                    liked_count=str(note_card_data.get("interactInfo", {}).get("likedCount", "0")),
                    shared_count=str(note_card_data.get("interactInfo", {}).get("sharedCount", "0")),
                    comment_count=str(note_card_data.get("interactInfo", {}).get("commentCount", "0")),
                    collected_count=str(note_card_data.get("interactInfo", {}).get("collectedCount", "0")),
                    collected=note_card_data.get("interactInfo", {}).get("collected", False),
                ),
                cover=Cover(
                    width=note_card_data.get("cover", {}).get("width", 0),
                    height=note_card_data.get("cover", {}).get("height", 0),
                    url=note_card_data.get("cover", {}).get("url", ""),
                    file_id=note_card_data.get("cover", {}).get("fileId", ""),
                    url_pre=note_card_data.get("cover", {}).get("urlPre", ""),
                    url_default=note_card_data.get("cover", {}).get("urlDefault", ""),
                    info_list=[
                        ImageInfo(
                            image_scene=i.get("imageScene", ""),
                            url=i.get("url", ""),
                        )
                        for i in note_card_data.get("cover", {}).get("infoList", [])
                    ],
                ),
            ),
            index=item.get("index", 0),
        ))
    return feeds


def adapt_feed_detail(note_card: Dict, note_id: str = "", xsec_token: str = "") -> FeedDetail:
    """API feed 详情响应 note_card → FeedDetail

    API GET /api/sns/web/v1/feed 返回的 note_card 结构:
      note_card.noteId, note_card.title, note_card.desc, note_card.type,
      note_card.time, note_card.ipLocation, note_card.user, note_card.interactInfo,
      note_card.imageList[].urlDefault / urlPre / width / height
    """
    image_list = []
    for img in note_card.get("imageList", []) or []:
        image_list.append(DetailImageInfo(
            width=img.get("width", 0),
            height=img.get("height", 0),
            url_default=img.get("urlDefault", ""),
            url_pre=img.get("urlPre", ""),
            live_photo=img.get("livePhoto", False),
        ))

    return FeedDetail(
        note_id=note_card.get("noteId", note_id),
        xsec_token=note_card.get("xsecToken", xsec_token),
        title=note_card.get("title", ""),
        desc=note_card.get("desc", ""),
        type=note_card.get("type", ""),
        time=note_card.get("time", 0),
        ip_location=note_card.get("ipLocation", ""),
        user=User.from_dict(note_card.get("user", {})),
        interact_info=InteractInfo.from_dict(note_card.get("interactInfo", {})),
        image_list=image_list,
    )


def adapt_comment(comment_data: Dict) -> Comment:
    """API 评论数据 → Comment"""
    return Comment(
        id=comment_data.get("id", ""),
        note_id=comment_data.get("noteId", ""),
        content=comment_data.get("content", ""),
        like_count=str(comment_data.get("likeCount", "0")),
        create_time=comment_data.get("createTime", 0),
        ip_location=comment_data.get("ipLocation", ""),
        liked=comment_data.get("liked", False),
        user_info=User.from_dict(comment_data.get("userInfo", {})),
        sub_comment_count=str(comment_data.get("subCommentCount", "0")),
        sub_comments=[adapt_comment(c) for c in comment_data.get("subComments", []) or []],
        show_tags=comment_data.get("showTags", []) or [],
    )


def adapt_comments(comments_data: Dict) -> CommentList:
    """API 评论响应 → CommentList

    API GET /api/sns/web/v2/comment/page 响应:
      comments_data.comments[] → Comment
      comments_data.cursor → cursor
      comments_data.has_more → hasMore
    """
    comments = [adapt_comment(c) for c in comments_data.get("comments", []) or []]
    return CommentList(
        list_=comments,
        cursor=comments_data.get("cursor", ""),
        has_more=comments_data.get("hasMore", False),
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
