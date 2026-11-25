"""검증 입력 만들기 — DB(읽기 전용)의 공고를 기관별 묶음(JSON Lines)으로 나눈다.

사용: python plan/validation/make_input.py --out data/validation/<실행>/in [--chunk 50] [--org nipa_business ...]
분류 프롬프트에 넣는 값과 같은 항목(app.services.classify.build_items: 제목·말머리·상태·기간·본문 앞 300자·첨부 이름)만 담는다.
본문 연락처는 가린다.
"""
import argparse
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from app.services.classify import build_items  # noqa: E402

ORGS = ["nipa_business", "nia_bid", "kca_bidding", "rapa_notice"]


def items(conn, board):
    ids = [r[0] for r in conn.execute(
        "SELECT a.ann_id FROM announcements a JOIN boards b ON b.board_id = a.board_id WHERE b.code = ? ORDER BY a.ann_id", (board,))]
    return build_items(conn, ids)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--chunk", type=int, default=50)
    ap.add_argument("--org", nargs="*", default=ORGS)
    a = ap.parse_args()
    conn = sqlite3.connect(f"file:{ROOT / 'data' / 'gongmo.db'}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    for board in a.org:
        allx = list(items(conn, board))
        d = Path(a.out) / board
        d.mkdir(parents=True, exist_ok=True)
        for i in range(0, len(allx), a.chunk):
            with open(d / f"chunk-{i // a.chunk + 1:02d}.jsonl", "w", encoding="utf-8") as f:
                for x in allx[i:i + a.chunk]:
                    f.write(json.dumps(x, ensure_ascii=False) + "\n")
        print(f"{board}: {len(allx)}건 → {-(-len(allx) // a.chunk)}묶음")


if __name__ == "__main__":
    main()
