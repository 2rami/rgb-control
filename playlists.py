"""재생목록과 대기열.

    이름 붙인 목록   "작업용" "게임용" 처럼 만들어 두고 한 번에 튼다
    대기열           지금 틀면서 뒤에 곡을 계속 쌓는다

playlists.json 에 남는다. 껐다 켜도 그대로다.

주소만 저장하고 제목은 나중에 채운다. 유튜브에 물어보는 데 몇 초 걸려서,
넣을 때마다 기다리면 붙여넣기가 답답해진다. 제목은 재생기가 곡을 열 때
알아낸 것을 돌려받아 채운다.
"""

import json
import time
import uuid
from pathlib import Path

SAVE = Path(__file__).with_name("playlists.json")

# 목록 하나에 담을 수 있는 곡 수. 유튜브 믹스를 통째로 받으면 끝이 없어서
# 어딘가에서 끊어야 한다.
MAX_ITEMS = 200
MAX_LISTS = 30


def _blank():
    return {"lists": [], "queue": [], "playing": None}


def load():
    try:
        data = json.loads(SAVE.read_text(encoding="utf-8"))
    except Exception:
        return _blank()
    out = _blank()
    if isinstance(data.get("lists"), list):
        out["lists"] = [x for x in data["lists"]
                        if isinstance(x, dict) and x.get("id") and x.get("name")]
    if isinstance(data.get("queue"), list):
        out["queue"] = [x for x in data["queue"] if isinstance(x, dict) and x.get("url")]
    out["playing"] = data.get("playing")
    return out


class Playlists:
    """목록과 대기열을 들고 있는다. 바뀔 때마다 파일에 남긴다."""

    def __init__(self):
        st = load()
        self.lists = st["lists"]
        self.queue = st["queue"]
        self.playing = st["playing"]     # 지금 트는 목록 id, 대기열이면 "queue"

    # ------------------------------------------------------------ 저장

    def _save(self):
        try:
            SAVE.write_text(json.dumps(
                {"lists": self.lists, "queue": self.queue, "playing": self.playing},
                indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass

    def snapshot(self):
        return {
            "lists": [{"id": l["id"], "name": l["name"],
                       "count": len(l.get("items", [])),
                       "items": l.get("items", [])} for l in self.lists],
            "queue": list(self.queue),
            "playing": self.playing,
        }

    # ------------------------------------------------------------ 목록

    def find(self, list_id):
        return next((l for l in self.lists if l["id"] == list_id), None)

    def create(self, name):
        if len(self.lists) >= MAX_LISTS:
            return None, f"목록은 {MAX_LISTS}개까지야"
        name = (name or "").strip() or f"목록 {len(self.lists) + 1}"
        item = {"id": uuid.uuid4().hex[:8], "name": name[:40], "items": []}
        self.lists.append(item)
        self._save()
        return item, f"'{item['name']}' 만들었어"

    def rename(self, list_id, name):
        l = self.find(list_id)
        if not l:
            return False, "그 목록이 없어"
        l["name"] = (name or "").strip()[:40] or l["name"]
        self._save()
        return True, "이름 바꿨어"

    def delete(self, list_id):
        before = len(self.lists)
        self.lists = [l for l in self.lists if l["id"] != list_id]
        if self.playing == list_id:
            self.playing = None
        self._save()
        return len(self.lists) < before, "지웠어"

    # ------------------------------------------------------------ 곡

    def add(self, list_id, url, title=None):
        """목록이나 대기열에 곡을 넣는다. list_id 가 'queue' 면 대기열."""
        url = (url or "").strip()
        if not url:
            return False, "주소가 비었어"

        target = self.queue if list_id == "queue" else None
        if target is None:
            l = self.find(list_id)
            if not l:
                return False, "그 목록이 없어"
            target = l.setdefault("items", [])

        if len(target) >= MAX_ITEMS:
            return False, f"한 목록에 {MAX_ITEMS}곡까지야"
        target.append({"url": url, "title": title or "", "at": int(time.time())})
        self._save()
        return True, "넣었어"

    def remove(self, list_id, index):
        target = self.queue if list_id == "queue" else (self.find(list_id) or {}).get("items")
        if target is None or not (0 <= index < len(target)):
            return False, "그 곡이 없어"
        target.pop(index)
        self._save()
        return True, "뺐어"

    def move(self, list_id, index, step):
        """곡 순서를 바꾼다. step 이 -1 이면 위로, 1 이면 아래로."""
        target = self.queue if list_id == "queue" else (self.find(list_id) or {}).get("items")
        if target is None or not (0 <= index < len(target)):
            return False, "그 곡이 없어"
        j = max(0, min(len(target) - 1, index + step))
        target.insert(j, target.pop(index))
        self._save()
        return True, "옮겼어"

    def clear_queue(self):
        self.queue = []
        self._save()
        return True, "대기열 비웠어"

    # ------------------------------------------------------------ 재생

    def urls_of(self, list_id):
        """그 목록의 주소들. 없으면 빈 목록."""
        if list_id == "queue":
            return [x["url"] for x in self.queue]
        l = self.find(list_id)
        return [x["url"] for x in (l.get("items", []) if l else [])]

    def set_playing(self, list_id):
        self.playing = list_id
        self._save()

    def note_title(self, url, title):
        """재생기가 알아낸 제목을 채워 넣는다.

        넣을 때 물어보면 붙여넣기가 몇 초씩 멎는다. 그래서 나중에 채운다.
        """
        if not title or title == url:
            return
        touched = False
        for bag in [self.queue] + [l.get("items", []) for l in self.lists]:
            for it in bag:
                if it.get("url") == url and not it.get("title"):
                    it["title"] = title[:120]
                    touched = True
        if touched:
            self._save()
