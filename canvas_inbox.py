from canvas_api import courses, endpoint, listing, local_timestamp, request, select_course
from queries import QueryUnavailable


def inbox(context, scope="inbox", course=None):
    params = {} if scope == "inbox" else {"scope": scope}
    if course is not None:
        selected = select_course(courses(context), course)
        params["filter[]"] = f"course_{selected['id']}"
    return [summary(row) for row in listing(context, "conversations", params)]


def recipients(context, keyword, course=None):
    if not keyword.strip():
        raise QueryUnavailable("请输入要查找的收件人姓名")
    params = {"search": keyword.strip(), "type": "user"}
    if course is not None:
        selected = select_course(courses(context), course)
        params["context"] = f"course_{selected['id']}"
    return [{"id": row["id"], "name": row["name"], "full_name": row.get("full_name"),
             "common_courses": row.get("common_courses", {})}
            for row in listing(context, "search/recipients", params)]


def conversation(context, thread_id):
    url = endpoint(f"conversations/{thread_id}", {"auto_mark_as_read": "false"})
    data, _ = request(context, url)
    if data["id"] != thread_id or not isinstance(data.get("messages"), list):
        raise QueryUnavailable("Canvas 未返回指定会话的消息列表")
    participants = {p["id"]: p["name"] for p in data["participants"]}
    messages = [message(row, participants) for row in data["messages"]]
    return [dict(summary(data), messages=messages, source=url)]


def summary(row):
    return {"id": row["id"], "title": row["subject"], "state": row["workflow_state"],
            "participants": [{"id": p["id"], "name": p["name"]} for p in row.get("participants") or []],
            "starred": row["starred"], "context": row.get("context_name"),
            "message_count": row["message_count"], "last_message": row.get("last_message"),
            "updated_at": local_timestamp(row.get("last_message_at"))}


def message(row, participants):
    return {"id": row["id"], "author_id": row["author_id"], "author": participants.get(row["author_id"]),
            "posted": local_timestamp(row["created_at"]), "body": row["body"],
            "attachments": [{"name": a.get("display_name") or a.get("filename"), "url": a.get("url")}
                            for a in row.get("attachments") or []],
            "media_comment": row.get("media_comment"),
            "forwarded": [message(m, participants) for m in row.get("forwarded_messages") or []]}
