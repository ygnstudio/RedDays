"""All presentation preferences for the generated calendars.

Change calendar look & feel here; no need to touch generate.py.
"""

CONFIG = {
    "tz": "Asia/Shanghai",
    "calendar_name": "中国节假日",
    "calendar_color": "#D0A9F5",
    # 逐日标注版：每一天都有事件，补班带具体时间与前一晚提醒
    "detailed": {
        "off_pattern": "{name} 假 {i}/{n}",
        "work_pattern": "{name} 补 {i}/{n}",
        "work_time": ("09:00", "18:00"),  # None 则补班为全天事件
        "work_alarm_min": 720,  # 提前 12h = 前一晚 21:00 提醒；None 则无提醒
        "attach_papers": True,  # 事件描述内嵌国务院公告链接
        "rich_description": True,  # 描述内嵌调休上下文：假期范围、共补几天/第几天、下一次补班
    },
    # 极简版：仅假期首日 + 补班日
    "minimal": {
        "off_pattern": "{name}（休）",
        "work_pattern": "{name}（班）",
        "work_time": None,
        "work_alarm_min": None,
        "attach_papers": False,
    },
    # 补班版：只有调休补班日，不含任何放假
    "workonly": {
        "off_pattern": "{name} 假 {i}/{n}",  # skip_off_days 下不产出，仅为键完整
        "work_pattern": "{name} 补 {i}/{n}",
        "work_time": ("09:00", "18:00"),
        "work_alarm_min": 720,
        "attach_papers": True,
        "rich_description": True,
        "skip_off_days": True,
    },
}
