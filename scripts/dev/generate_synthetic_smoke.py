#!/usr/bin/env python3
import argparse
import json
import re
import sys
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts._common.jsonl_utils import write_jsonl
from scripts._common.schema_utils import SCHEMA_VERSION

SIZE_ARCS = {"tiny": 1, "standard": 3, "stress": 10}
TYPE_CODES = {
    "text": 1,
    "image": 3,
    "voice": 34,
    "video": 43,
    "sticker": 47,
    "location": 48,
    "contact": 42,
    "link_or_file": 49,
    "system": 10000,
}
EVENTS = [
    ("ME", "text", "早上好，我今天想用更轻松的方式聊一下最近的节奏。", {}, 0),
    ("OTHER", "text", "早，我也愿意好好聊，不想让昨天的小误会继续拖着。", {}, 6),
    ("ME", "image", "发了一张早餐和便签的图片。", {"image_kind": "breakfast"}, 8),
    ("OTHER", "sticker", "发了一个点头回应的表情。", {"intent": "acknowledge"}, 4),
    ("ME", "text", "我不是要催你，只是想知道我们今天大概怎么安排。", {}, 10),
    ("OTHER", "voice", "我上午会比较忙，但中午前可以确认时间。", {"emotion": ["NEUTRAL"], "event": ["planning"]}, 11),
    ("ME", "text", "可以，那我先把下午空出来，不急着定死。", {}, 9),
    ("OTHER", "link_or_file", "分享了一篇关于沟通节奏的小文章。", {"link_sub_type": "link"}, 20),
    ("ME", "link_or_file", "引用刚才的文章内容，说明自己在意的是确认感。", {"link_sub_type": "quote", "quote_text": "稳定沟通不是秒回，而是让对方知道大致方向。"}, 5),
    ("OTHER", "text", "我理解，你要的不是立刻回复，而是不要突然没消息。", {}, 6),
    ("ME", "location", "发送了一个虚构见面地点。", {}, 40),
    ("OTHER", "text", "这个地点可以，我下班后过去会顺路。", {}, 7),
    ("ME", "text", "如果你临时改时间，提前说一声就好。", {}, 30),
    ("OTHER", "text", "我刚刚看到这句有点紧张，担心你觉得我总是不可靠。", {}, 18),
    ("ME", "link_or_file", "引用第 13 条消息，解释不是指责。", {"link_sub_type": "quote", "quote_text": "如果你临时改时间，提前说一声就好。"}, 5),
    ("OTHER", "voice", "我刚才语气可能防御了，我不是想顶回去。", {"emotion": ["SAD"], "event": ["repair"]}, 9),
    ("ME", "text", "谢谢你说明，我也会注意不要把担心说得像质问。", {}, 8),
    ("OTHER", "sticker", "发了一个缓和气氛的表情。", {"intent": "ease_tension"}, 3),
    ("ME", "image", "发了一张日程截图。", {"image_kind": "schedule_doc", "content_type": "TYPE_D_DOC"}, 14),
    ("OTHER", "text", "我看到了，六点半之后比较稳。", {}, 6),
    ("ME", "video", "发了一个路上短视频。", {}, 70),
    ("OTHER", "text", "视频里那条路我认识，过去大概二十分钟。", {}, 8),
    ("ME", "link_or_file", "发送了一个虚构的计划文档。", {"link_sub_type": "file"}, 11),
    ("OTHER", "text", "计划不用太满，留一点聊天和散步的时间就好。", {}, 9),
    ("ME", "system", "系统提示：中间有一段较长时间没有新消息。", {"break_type": "time_gap"}, 360),
    ("ME", "text", "我刚忙完，才看到你前面那句，抱歉让你等了。", {}, 5),
    ("OTHER", "text", "没关系，你说明一下我就安心很多。", {}, 8),
    ("ME", "contact", "分享了一个虚构联系人名片。", {}, 9),
    ("OTHER", "text", "这个朋友如果也来，我们就把地点选得更方便一点。", {}, 8),
    ("ME", "voice", "我其实有点担心多人场合会让我们没机会单独聊。", {"emotion": ["NEUTRAL", "ANXIOUS"], "event": ["boundary"]}, 7),
    ("OTHER", "link_or_file", "引用语音大意，确认边界。", {"link_sub_type": "quote", "quote_text": "担心多人场合没有机会单独聊。"}, 6),
    ("ME", "text", "对，我希望至少留半小时只聊我们自己的事情。", {}, 6),
    ("OTHER", "image", "发了一张咖啡店外观照片。", {"image_kind": "cafe"}, 20),
    ("ME", "sticker", "发了一个表示赞同的表情。", {"intent": "agree"}, 5),
    ("OTHER", "link_or_file", "分享了一个虚构小程序预约页。", {"link_sub_type": "miniprogram"}, 10),
    ("ME", "text", "那我们就按这个来，变动也及时说。", {}, 6),
    ("OTHER", "video", "发了一个到达附近的短视频。", {}, 45),
    ("ME", "text", "看到啦，我十分钟后到。", {}, 5),
    ("OTHER", "voice", "今天这样沟通我觉得比昨天舒服很多。", {"emotion": ["HAPPY"], "event": ["closure"]}, 8),
    ("ME", "text", "我也这么觉得，之后我们就按这种方式慢慢调整。", {}, 7),
    ("OTHER", "text", "好，今天先轻松见面，不把问题都堆在一口气里解决。", {}, 6),
]


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--size", choices=SIZE_ARCS, default="tiny")
    parser.add_argument("--seed", default="20260504")
    parser.add_argument("--review-pack", action="store_true")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--output-root", type=Path, default=PROJECT_ROOT)
    return parser.parse_args()


def output_layout(args):
    if args.output:
        root = args.output if args.output.is_absolute() else PROJECT_ROOT / args.output
    elif args.review_pack:
        root = PROJECT_ROOT / "research" / "big_plan" / "plan_v4" / "a1_review_pack"
    else:
        root = args.output_root / "advisor_out" / "synthetic_smoke"
    root = root.resolve()
    return {
        "root": root,
        "raw": root / f"synthetic_raw_{args.size}.jsonl",
        "artifacts": root / "artifacts",
        "timeline": root / "timeline",
        "reports": root / "reports",
    }


def format_time(dt):
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def next_media_path(counts, modality):
    counts[modality] += 1
    ext = {"image": "jpg", "voice": "mp3", "video": "mp4", "sticker": "gif"}[modality]
    return f"{modality}/syn_{modality}_{counts[modality]:03d}.{ext}"


def generate_messages(size):
    messages = []
    media_counts = Counter()
    seq = 0
    base_time = datetime(2026, 1, 8, 8, 10, 0)
    for arc in range(SIZE_ARCS[size]):
        current = base_time + timedelta(days=arc * 5)
        for speaker, modality, text, extra, delta in EVENTS:
            current += timedelta(minutes=delta)
            seq += 1
            msg_uid = f"synthetic:{size}:{seq:06d}"
            msg = {
                "seq_in_html": seq,
                "msg_uid": msg_uid,
                "MsgSvrID": f"syn_svr_{seq:012d}",
                "token": f"syn_token_{seq:06d}",
                "ts": int(current.timestamp()),
                "time_local": format_time(current),
                "speaker": speaker,
                "type": TYPE_CODES[modality],
                "sub_type": 0,
                "modality": modality,
                "text_raw": text if arc == 0 else f"第 {arc + 1} 轮亲密关系沟通：{text}",
                "media_path": None,
                "synthetic_scene": f"intimate_relationship_arc_{arc + 1}",
            }
            if modality in {"image", "voice", "video", "sticker"}:
                msg["media_path"] = next_media_path(media_counts, modality)
            if modality == "link_or_file":
                msg["link_sub_type"] = extra["link_sub_type"]
                msg["sub_type"] = {"quote": 57, "link": 5, "file": 6, "miniprogram": 33}.get(extra["link_sub_type"], 0)
            if modality == "location":
                msg.update({"location_label": "示例地点北门", "location_poiname": "示例地点", "location_x": 116.321, "location_y": 39.912})
            if modality == "contact":
                msg.update({"contact_nickname": "示例联系人A", "contact_username": "synthetic_contact_a"})
            if modality == "system":
                msg["break_type"] = extra.get("break_type", "system_notice")
            msg.update({f"_synthetic_{k}": v for k, v in extra.items()})
            messages.append(msg)
    return messages


def header_from_msg(msg):
    return {k: msg.get(k) for k in ["seq_in_html", "msg_uid", "MsgSvrID", "token", "ts", "time_local", "speaker", "type", "sub_type", "modality", "media_path"]}


def image_artifact(msg, index, non_normal_used):
    content_type = "TYPE_C_NORMAL"
    if not non_normal_used and msg.get("_synthetic_content_type"):
        content_type = msg["_synthetic_content_type"]
        non_normal_used = True
    kind = msg.get("_synthetic_image_kind", "photo")
    return {
        **header_from_msg(msg), "schema_version": SCHEMA_VERSION, "route_class": "SCREENSHOT" if kind == "schedule_doc" else "PHOTO",
        "content_type": content_type, "triage_confidence": 0.94, "nsfw_score": 0.01, "sfw_score": 0.99, "text_score": 0.62 if kind == "schedule_doc" else 0.18,
        "ok": True, "width": 1280, "height": 960, "is_long_image": False, "ocr_text": f"synthetic OCR {index}: 时间、地点、确认方式均为虚构。",
        "need_ocr": kind == "schedule_doc", "caption": f"一张用于说明亲密关系沟通场景的虚构{kind}图片。", "expert_used": "synthetic-vlm",
        "is_fallback": False, "ensemble_mode": "synthetic", "ensemble_used": False, "caption_model": "synthetic-vlm",
        "image_summary": f"图片表达了本轮沟通中的{kind}线索，用于帮助双方确认安排。", "scene_focus": "安排确认", "emotion_atmosphere": "温和", "intent": "补充上下文",
        "compression_ratio": 1.0, "is_compressed": True,
    }, non_normal_used


def sticker_artifact(msg, index):
    intent = msg.get("_synthetic_intent", "acknowledge")
    return {**header_from_msg(msg), "schema_version": SCHEMA_VERSION, "caption": f"虚构表情 {index}：用来表达{intent}。", "ocr_text": "", "sticker_summary": f"表情用于{intent}，缓和亲密关系沟通氛围。", "intent": intent, "intent_confidence": 0.91, "sticker_class": "animated", "is_animated": True, "n_frames": 12, "content_type": "TYPE_C_NORMAL", "is_sensitive": False}


def voice_artifact(msg, index):
    emotions = msg.get("_synthetic_emotion", ["NEUTRAL"])
    events = msg.get("_synthetic_event", ["conversation"])
    return {**header_from_msg(msg), "schema_version": SCHEMA_VERSION, "primary_engine": "synthetic-asr", "raw_text": msg["text_raw"], "punct_text": msg["text_raw"], "funasr": {"patches": []}, "sensevoice": {"emotion_tags": emotions, "event_tags": events}, "trigger_reasons": ["synthetic intimate relationship smoke sample"], "voice_analysis": {"emotion_desc": "语气克制，表达愿意修复和确认边界。", "subtext": "希望对方理解需求，同时避免升级冲突。"}}


def video_artifact(msg, index):
    return {**header_from_msg(msg), "schema_version": SCHEMA_VERSION, "metadata": {"duration_sec": 8 + index, "width": 1280, "height": 720, "fps": 25, "has_audio": True}, "transcription": {"punct_text": msg["text_raw"], "engine": "synthetic-asr", "segments": []}, "emotion": {"sensevoice": {"emotion_tags": ["NEUTRAL"], "event_tags": ["planning"]}, "trigger_reasons": ["synthetic video context"], "voice_analysis": {"emotion_desc": "轻松说明当前位置。"}}, "video_understanding": {"summary": "短视频展示虚构地点附近的路况和到达状态。", "events": ["到达附近", "确认路线"]}, "video_summary": "视频用于补充线下见面安排的上下文。", "is_compressed": True, "compression_ratio": 1.0, "video_atmosphere": "轻松", "video_intent": "说明进展", "keyframes": [{"frame_id": 1, "caption": "虚构街景关键帧"}], "content_type": "TYPE_C_NORMAL", "triage_confidence": 0.96, "audit": {"synthetic": True}}


def linkfile_artifact(msg, index):
    sub = msg["link_sub_type"]
    rec = {**header_from_msg(msg), "schema_version": SCHEMA_VERSION, "link_sub_type": sub}
    if sub == "quote":
        rec.update({"quote_svrid": f"syn_quote_{index:06d}", "quote_type": "text", "quote_text": msg.get("_synthetic_quote_text", "虚构引用文本")})
    elif sub == "link":
        rec.update({"link_url": f"https://example.invalid/synthetic/intimate-communication-{index}", "link_title": "虚构亲密关系沟通文章", "link_type": "article"})
    elif sub == "file":
        rec.update({"file_name": "weekend_plan.pdf", "file_ext": ".pdf", "file_category": "document", "file_size_bytes": 204800, "file_summary": "虚构周末安排文档摘要。"})
    elif sub == "miniprogram":
        rec.update({"link_url": "https://example.invalid/synthetic/booking", "link_title": "虚构预约小程序", "miniprogram_appid": "wxsyntheticdemo000", "miniprogram_name": "合成预约"})
    return rec


def build_artifacts(messages):
    artifacts = {"image": [], "sticker": [], "voice": [], "video": [], "linkfile": []}
    non_normal_used = False
    for idx, msg in enumerate(messages, 1):
        if msg["modality"] == "image":
            rec, non_normal_used = image_artifact(msg, idx, non_normal_used)
            artifacts["image"].append(rec)
        elif msg["modality"] == "sticker":
            artifacts["sticker"].append(sticker_artifact(msg, idx))
        elif msg["modality"] == "voice":
            artifacts["voice"].append(voice_artifact(msg, idx))
        elif msg["modality"] == "video":
            artifacts["video"].append(video_artifact(msg, idx))
        elif msg["modality"] == "link_or_file":
            artifacts["linkfile"].append(linkfile_artifact(msg, idx))
    return artifacts


def strip_synthetic_fields(records):
    return [{k: v for k, v in item.items() if not k.startswith("_synthetic_")} for item in records]


def artifact_by_uid(records):
    return {item["msg_uid"]: item for item in records}


def build_timelines(messages, artifacts):
    lookups = {k: artifact_by_uid(v) for k, v in artifacts.items()}
    full, slim = [], []
    for msg in messages:
        item = {k: v for k, v in msg.items() if not k.startswith("_synthetic_")}
        thin = {"msg_uid": msg["msg_uid"], "ts": msg["ts"], "time_local": msg["time_local"], "speaker": msg["speaker"], "modality": msg["modality"], "text": msg["text_raw"]}
        uid = msg["msg_uid"]
        if uid in lookups["image"]:
            img = lookups["image"][uid]
            item.update({"image_content_type": img["content_type"], "image_ocr_text": img["ocr_text"], "image_summary": img["image_summary"], "image_intent": img["intent"], "image_emotion_atmosphere": img["emotion_atmosphere"]})
            thin.update({"text": img["image_summary"], "image_summary": img["image_summary"], "image_intent": img["intent"], "content_type": img["content_type"]})
        if uid in lookups["sticker"]:
            st = lookups["sticker"][uid]
            item.update({"sticker_summary": st["sticker_summary"], "sticker_intent": st["intent"], "sticker_ocr_text": st["ocr_text"]})
            thin.update({"sticker_summary": st["sticker_summary"], "sticker_intent": st["intent"], "sticker_ocr_text": st["ocr_text"]})
        if uid in lookups["voice"]:
            vc = lookups["voice"][uid]
            item.update({"voice_to_text": vc["punct_text"], "asr_engine": vc["primary_engine"], "emotion_tags": vc["sensevoice"]["emotion_tags"], "event_tags": vc["sensevoice"]["event_tags"], "voice_analysis": vc["voice_analysis"], "emotion_desc": vc["voice_analysis"]["emotion_desc"]})
            thin.update({"text": vc["punct_text"], "emotion_tags": vc["sensevoice"]["emotion_tags"], "emotion_desc": vc["voice_analysis"]["emotion_desc"], "subtext": vc["voice_analysis"]["subtext"]})
        if uid in lookups["video"]:
            vd = lookups["video"][uid]
            item.update({"video_summary": vd["video_summary"], "video_voice_to_text": vd["transcription"]["punct_text"], "video_emotion_tags": vd["emotion"]["sensevoice"]["emotion_tags"], "video_atmosphere": vd["video_atmosphere"], "video_intent": vd["video_intent"]})
            thin.update({"video_summary": vd["video_summary"], "video_voice_to_text": vd["transcription"]["punct_text"], "video_emotion_tags": vd["emotion"]["sensevoice"]["emotion_tags"], "video_atmosphere": vd["video_atmosphere"], "video_intent": vd["video_intent"]})
        if uid in lookups["linkfile"]:
            lf = lookups["linkfile"][uid]
            link_timeline_fields = {
                "link_sub_type": "link_sub_type",
                "quote_svrid": "link_quote_svrid",
                "quote_type": "link_quote_type",
                "quote_text": "link_quote_text",
                "link_url": "link_url",
                "link_title": "link_title",
                "link_type": "link_type",
                "file_ext": "link_file_ext",
                "file_summary": "link_file_summary",
                "file_name": "link_file_name",
                "file_category": "link_file_category",
                "file_size_bytes": "link_file_size_bytes",
                "miniprogram_appid": "link_miniprogram_appid",
                "miniprogram_name": "link_miniprogram_name",
                "content_title": "link_content_title",
            }
            for key, timeline_key in link_timeline_fields.items():
                if key in lf:
                    item[timeline_key] = lf[key]
                    thin[timeline_key] = lf[key]
        full.append(item)
        slim.append(thin)
    return full, slim


def scan_records(records):
    text = "\n".join(json.dumps(item, ensure_ascii=False) for item in records)
    private_marker = "/" + "data/" + "wechatDHA/"
    return {"phone_like_hits": len(re.findall(r"(?<!\\d)1[3-9]\\d{9}(?!\\d)", text)), "secret_like_hits": len(re.findall(r"(?:sk|ant|hy)-[A-Za-z0-9_-]{20,}|AIza[A-Za-z0-9_-]{20,}", text)), "private_path_hits": text.count(private_marker)}


def write_reports(layout, args, messages, artifacts, full, slim):
    modality_counts = Counter(msg["modality"] for msg in messages)
    content_counts = Counter(item.get("content_type", "") for item in artifacts["image"] + artifacts["sticker"] + artifacts["video"])
    generated = datetime.now().isoformat(timespec="seconds")
    coverage = [f"# A1 Synthetic Review Pack Coverage", "", f"- size: `{args.size}`", f"- seed: `{args.seed}`", f"- generated_at: `{generated}`", f"- raw_messages: `{len(messages)}`", f"- full_timeline: `{len(full)}`", f"- slim_timeline: `{len(slim)}`", "", "## Modality counts", ""]
    coverage.extend(f"- {k}: {v}" for k, v in sorted(modality_counts.items()))
    coverage.extend(["", "## Artifact counts", ""])
    coverage.extend(f"- {k}: {len(v)}" for k, v in sorted(artifacts.items()))
    coverage.extend(["", "## Content type counts", ""])
    coverage.extend(f"- {k}: {v}" for k, v in sorted(content_counts.items()) if k)
    safety = scan_records(messages + full + slim + sum(artifacts.values(), []))
    safety_md = ["# A1 Synthetic Review Pack Safety", "", f"- phone_like_hits: `{safety['phone_like_hits']}`", f"- secret_like_hits: `{safety['secret_like_hits']}`", f"- private_path_hits: `{safety['private_path_hits']}`", "- real_media_files: `0`", "- real_backup_content_used: `0`"]
    flow = ["# A1 Flow Draft", "", "```bash", f"conda run -n wechatDHA python scripts/dev/generate_synthetic_smoke.py --size {args.size} --seed {args.seed} --review-pack --output {layout['root'].relative_to(PROJECT_ROOT)}", "```", "", "A1 only generates review materials. It does not run full synthetic smoke."]
    (layout["reports"] / "coverage_report.md").write_text("\n".join(coverage) + "\n", encoding="utf-8")
    (layout["reports"] / "safety_report.md").write_text("\n".join(safety_md) + "\n", encoding="utf-8")
    (layout["reports"] / "flow_draft.md").write_text("\n".join(flow) + "\n", encoding="utf-8")
    (layout["root"] / "manifest.json").write_text(json.dumps({"size": args.size, "seed": args.seed, "messages": len(messages), "artifacts": {k: len(v) for k, v in artifacts.items()}, "safety": safety}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main():
    args = parse_args()
    layout = output_layout(args)
    messages = generate_messages(args.size)
    artifacts = build_artifacts(messages)
    raw_messages = strip_synthetic_fields(messages)
    full, slim = build_timelines(messages, artifacts)
    for path in [layout["artifacts"], layout["timeline"], layout["reports"]]:
        path.mkdir(parents=True, exist_ok=True)
    write_jsonl(str(layout["raw"]), raw_messages)
    for name, records in artifacts.items():
        write_jsonl(str(layout["artifacts"] / f"{name}_merged_final.synthetic.jsonl"), records)
    write_jsonl(str(layout["timeline"] / "enriched_full.synthetic.jsonl"), full)
    write_jsonl(str(layout["timeline"] / "enriched_slim.synthetic.jsonl"), slim)
    write_reports(layout, args, raw_messages, artifacts, full, slim)
    print(json.dumps({"output": str(layout["root"]), "size": args.size, "messages": len(messages)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
