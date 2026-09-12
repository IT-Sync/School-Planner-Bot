"""Portable RFC 5545 calendar export of resolved occurrences."""

from datetime import datetime, timezone
from zoneinfo import ZoneInfo


def escape(value):
    return (
        str(value or "")
        .replace("\\", "\\\\")
        .replace("\r\n", "\n")
        .replace("\r", "\n")
        .replace("\n", "\\n")
        .replace(";", "\\;")
        .replace(",", "\\,")
    )


def fold(line):
    parts, current = [], ""
    for char in line:
        if len((current + char).encode("utf-8")) > 75:
            parts.append(current)
            current = " "
        current += char
    return "\r\n".join([*parts, current])


def export_calendar(profile, days, tz):
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//IT-Sync//School Planner//RU",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "X-WR-CALNAME:" + escape(profile["name"]),
    ]
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    for day in days:
        for event in day["entries"]:
            if event.get("cancelled"):
                continue

            def at(value, target=day["date"]):
                return (
                    datetime.combine(target, value, ZoneInfo(tz))
                    .astimezone(timezone.utc)
                    .strftime("%Y%m%dT%H%M%SZ")
                )

            lines.extend(
                [
                    "BEGIN:VEVENT",
                    f"UID:{profile['id']}-{event['id']}-{day['date'].isoformat()}@school-planner",
                    "DTSTAMP:" + stamp,
                    "DTSTART:" + at(event["start_time"]),
                    "DTEND:" + at(event["end_time"]),
                    "SUMMARY:" + escape(event["label"]),
                    "LOCATION:" + escape(event.get("location")),
                    "DESCRIPTION:" + escape(event.get("subtitle")),
                    "END:VEVENT",
                ]
            )
    lines.append("END:VCALENDAR")
    return "\r\n".join(fold(line) for line in lines) + "\r\n"
