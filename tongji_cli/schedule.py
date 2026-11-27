from datetime import timedelta

from tongji_cli.canvas import api as canvas_api
from tongji_cli.canvas.assignments import assignments
from tongji_cli.jw.timetable import timetable, timetable_range


def schedule_items(args, site, context, page, day):
    if args.command == "today":
        return assignments(context, day) if site == "canvas" else timetable(page, day)
    if site == "canvas":
        return canvas_api.tasks(context, day, 7)
    return timetable_range(page, [day + timedelta(days=i) for i in range(7)])


def week_view(results, start):
    by_day = {(start + timedelta(days=i)).isoformat(): {} for i in range(7)}
    for row in results["jw"].get("items", []):
        by_day[row["date"]].update(classes=row["items"], timetable_source=row["source"])
    if "items" in results["canvas"]:
        for row in by_day.values():
            row["assignments"] = []
        for row in results["canvas"]["items"]:
            by_day[row["due"][:10]]["assignments"].append(row)
    status = "ok" if all("items" in entry for entry in results.values()) else "partial"
    summary = {site: {k: v for k, v in entry.items() if k != "items"} for site, entry in results.items()}
    summary["week"] = {"status": status, "items": [{"date": day, **row} for day, row in by_day.items()]}
    return summary
