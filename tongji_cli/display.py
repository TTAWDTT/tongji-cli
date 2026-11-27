import json


def display(results, as_json):
    if as_json:
        print(json.dumps(results, ensure_ascii=False))
    else:
        for site, entry in results.items():
            print(f"{site}: {entry['status']}")
            if "after_restart" in entry:
                print(f"重开专用浏览器后: {entry['after_restart']}")
            if entry.get("scope"):
                print(entry["scope"])
            if "detail" in entry:
                print(entry["detail"])
            if entry.get("errors"):
                print("部分课程未能核实：")
                for error in entry["errors"]:
                    print_record(error)
            if entry.get("undated_assignments"):
                print("学习通截止时间未知的作业：")
                for item in entry["undated_assignments"]:
                    print_record(item)
            if "items" in entry:
                if site == "chaoxing" and entry["status"] == "partial":
                    count = len(entry["items"])
                    print(f"已核实 {count} 项" if count else "暂未取得可核实的条目")
                else:
                    print(f"共 {len(entry['items'])} 项")
                for item in entry["items"]:
                    print_record(item)
    ok = all(entry["status"] in {"authenticated", "ok"} and
             entry.get("after_restart", "authenticated") == "authenticated" for entry in results.values())
    return 0 if ok else 1


FIELD_LABELS = {
    "chaoxing_assignments": "学习通作业", "undated_assignments": "截止时间未知的作业",
    "due_as_listed": "官方作答时间原文", "class_id": "班级 ID", "courses_checked": "已查课程数",
    "assignment_receipt": "本人作业回执", "menu_path": "菜单路径", "syllabus_id": "大纲编号",
    "candidate_windows": "达到最短预约时长的空档", "receipt_id": "回执编号",
    "topic_options": "可选申请主题", "topic": "申请主题", "purpose_filled": "已填写申请内容",
    "occupied": "已占时段", "unoccupied": "未被占用的时段", "open_hours": "开放时段",
    "min_minutes": "最短时长（分钟）", "max_minutes": "最长时长（分钟）",
    "min_people": "最少人数", "max_people": "最多人数", "form_fields": "申请表项目",
    "room_id": "空间编号", "room_name": "空间名称", "room_type": "空间类型", "selected": "当前选中",
    "seat_type": "座位类型", "periods": "馆方开放查询的预约周期", "start_date": "起始日期", "end_date": "截止日期",
    "permission": "本账号该期预约权限", "seat_numbers": "空闲座位号",
    "included": "导出内容", "filename": "文件名",
    "completion_status": "是否完成", "start_time": "开始时间", "end_time": "结束时间",
    "group_id": "小组 ID", "group_name": "小组名称", "published": "已发布",
    "teacher": "主讲教师", "last_studied": "上次学习", "task_count": "任务数",
    "electricity_unit": "电量单位", "unit_price_yuan_per_kwh": "单价（元/度）",
    "water_unit": "水量单位", "remaining_water": "房间剩余水量", "used_water": "用水量", "unit_price_yuan_per_tonne": "单价（元/吨）",
    "remaining_electricity": "房间剩余电量", "purchased_electricity": "房间累计购电量", "used_electricity": "用电量",
    "campus_query": "校内水电查询入口", "images": "配图", "index": "序号", "links": "链接", "readings": "逐日用量记录",
    "recorded_at": "校方记录时间", "startDate": "起始日期", "endDate": "截止日期",
    "totals_hidden": "课程隐藏总评", "marks": "本人选课成绩", "current_score": "当前得分（%）",
    "current_grade": "当前等级", "final_score": "计入未评分作业后的得分（%）", "final_grade": "计入未评分作业后的等级",
    "weighted": "按组加权", "groups": "作业分组", "weight_percent": "分组权重（%）",
    "drop_lowest": "舍去最低项数", "drop_highest": "舍去最高项数", "never_drop": "不参与本组舍分的作业 ID",
    "points_possible": "满分", "omit_from_final_grade": "从总评排除",
    "rubric": "评分量规", "criteria": "评分标准", "ratings": "等级", "points": "分值", "used_for_grading": "用于评分",
    "description": "说明", "long_description": "详细说明", "criterion_use_range": "按区间评分",
    "ignore_for_scoring": "从评分排除", "free_form_comments": "自由评语", "has_content": "提供了大纲内容",
    "recipient_id": "收件人 ID", "recipient_ids": "收件人 ID", "message_id": "消息 ID",
    "editor_checked": "已核对编辑框", "attribute": "设置项", "previous": "变更前的值", "target": "目标值",
    "last_message": "最近消息", "updated_at": "更新时间", "starred": "星标", "context": "所属课程或小组",
    "message_count": "消息数", "messages": "消息", "participants": "参与者", "author": "发送人", "author_id": "发送人 ID",
    "attachment_details": "附件详情", "attachment_id": "附件 ID", "attempt": "提交次数",
    "forwarded": "转发的消息", "attachments": "附件", "media_comment": "媒体留言", "state": "状态",
    "id": "ID", "title": "名称", "course": "课程", "instructions": "作业要求", "date": "日期",
    "period": "节次", "campus": "校区", "detail": "内容", "locations_as_listed": "课表地点",
    "submitted": "已提交", "due": "截止", "url": "链接", "source": "来源", "code": "编号",
    "course_id": "课程 ID", "submission_state": "提交状态", "submission_types": "提交方式",
    "channel_id": "渠道 ID", "channel_type": "渠道类型", "channel_state": "渠道状态",
    "notification": "通知项", "frequency": "通知频率", "body": "正文", "posted": "发布时间", "module": "模块", "type": "类型", "source_url": "来源",
    "semester_id": "校历学期编号", "year": "学年起始年份",
    "teaching_week_start": "教学开始周", "teaching_week_end": "教学结束周",
    "exam_week_start": "考试开始周", "exam_week_end": "考试结束周",
    "semester": "学期", "week": "周次", "day_type": "校历标记", "classes": "课表",
    "assignments": "作业", "items": "条目", "week_start": "周一", "week_end": "周日",
    "floor": "楼层", "area": "区域", "seat": "座位号", "available": "空余", "total": "总数",
    "booking_available": "当前可提交", "booking_button": "馆方按钮", "receipt": "回执",
    "term": "学期", "dorm_building": "宿舍楼", "dorm_room": "宿舍号",
    "venue": "场馆", "sport": "项目", "field": "场地", "facility": "医疗机构", "building": "教学楼", "parent_id": "父回复 ID",
    "copies": "逐册馆藏", "locations": "各馆藏地",
    "previous_due_date": "原应还日期", "barcode": "条码号", "returned_date": "实还日期", "due_date": "应还日期", "borrowed_date": "借阅日期",
    "observed_at": "查询时间", "time_slot": "时段", "branch": "馆区", "hours": "开放时间", "areas": "分区", "bibliography": "书目信息", "search_url": "检索页",
    "audience": "适用人群", "steps": "办理步骤", "notes": "说明", "materials": "所需材料", "guide": "指南",
    "keyword": "关键词", "rooms": "教室列表", "status": "状态", "usage": "教室情况", "study_time": "自习可用时长",
    "booking": "场次", "amount": "金额",
    "department": "部门", "category": "分类", "line": "线路", "regular_source": "常规时刻表",
    "calendar_source": "校历来源", "room": "教室", "schedule": "安排", "action": "操作",
    "departures": "发车时刻", "stop_source": "候车点调整公告",
    "timetable_source": "教务原课表", "teaching_week": "教学周", "departure": "计划发车", "stop": "上车点", "from": "从", "to": "到",
}


def print_record(row, indent="  "):
    if not isinstance(row, dict):
        print(indent + str(row))
        return
    for key, value in row.items():
        label = FIELD_LABELS.get(key, key)
        if isinstance(value, dict):
            print(f"{indent}{label}")
            print_record(value, indent + "  ")
        elif isinstance(value, list) and value and isinstance(value[0], dict):
            print(f"{indent}{label}（{len(value)}）")
            for item in value:
                print_record(item, indent + "  ")
        else:
            if isinstance(value, list):
                value = "、".join(map(str, value)) or "无"
            elif value is None:
                value = "未提供"
            elif isinstance(value, bool):
                value = "是" if value else "否"
            print(f"{indent}{label}  {value}")
    if indent == "  ":
        print()
