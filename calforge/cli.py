"""Dòng lệnh: python -m calforge <lệnh> ...

  facts   --year 2027                    xem dữ kiện ngày lễ bơm vào prompt
  ideate  "keyword" [--pick r1a2,r1a4]   keyword -> góc tiếp cận -> concept.json
          [--more] [--style "..."] [--manual]
  angles  "keyword"                      liệt kê các góc đã sinh cho keyword
  check   <thư mục concept>              kiểm tra lại concept.json
  plan    <thư mục concept>              jobs.json + CSV cho chatgpt-automation
  import  <thư mục concept>              nhận ảnh chatgpt-automation đã gen về _he_thong/anh_ai/
  render  <thư mục concept> [--months 1,3] [--placeholder-art ảnh.png]
                                         dựng bìa + trang ảnh + trang lưới + PDF printable
  gen     <thư mục concept>              gen ảnh qua ChatGPT web (song song nhiều tài khoản)
  upscale <thư mục concept>              Real-ESRGAN lên đủ khổ in
  listing <thư mục concept>              title / mô tả / tag
  printify <thư mục concept> [--publish] upload + tạo sản phẩm NHÁP
  produce <thư mục concept>              gen -> upscale -> render -> listing -> Printify
  run     "keyword"                      TRỌN GÓI: keyword -> sản phẩm
  ui      [--port 8080] [--no-browser]   mở giao diện web CalForge Studio
  accounts                               xem danh sách tài khoản ChatGPT
  login   <profile>                      mở Chrome để đăng nhập tài khoản
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import products

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
if sys.stderr and hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from . import config
from .core import dates
from .ideation.pipeline import run_ideation_batched, slugify
from .ideation.validate import validate_concept
from . import layout
from .imagegen import plan
from .llm.base import AwaitingResponse


def _concept_dir(arg: str) -> Path:
    p = Path(arg)
    if p.name == "concept.json":                 # cho phép trỏ thẳng tới <cuốn>/_he_thong/concept.json
        p = p.parent.parent if p.parent.name == layout.SYSTEM else p.parent
    if not layout.is_book(p):
        sys.exit(f"Không thấy cuốn lịch ({layout.SYSTEM}/concept.json) trong {p}")
    return p


def cmd_facts(args, cfg):
    print(dates.calendar_facts(args.year or cfg["year"], args.market or cfg["market"]))


def cmd_ideate(args, cfg):
    if args.manual:
        cfg["llm"]["backend"] = "manual"
    backend = config.make_backend(cfg)
    try:
        res = run_ideation_batched(
            args.keyword, backend, Path(cfg["projects_dir"]),
            year=args.year or cfg["year"], market=args.market or cfg["market"],
            n_angles=cfg["angles_per_keyword"], more=args.more,
            pick=args.pick.split(",") if args.pick else None,
            auto_pick=args.auto or cfg["auto_pick"], style=args.style, max_repairs=cfg["max_repairs"],
            family=args.family, grid_preset=args.grid_preset,
            keyword_root=products.root(cfg["projects_dir"]))
    except AwaitingResponse as w:
        print("Đang chờ câu trả lời của ChatGPT (chế độ thủ công):")
        print(f"  1. Mở và copy prompt:  {w.prompt_path}")
        print("  2. Dán vào ChatGPT (P1, P2 và các lần sửa nên dán trong CÙNG một chat)")
        print(f"  3. Lưu nguyên câu trả lời vào: {w.response_path}")
        print("  4. Chạy lại đúng lệnh này - tool đi tiếp từ chỗ dừng.")
        return
    print(f"Keyword: {args.keyword} -> {res.keyword_dir}")
    print(f"Tổng số góc tiếp cận: {len(res.angles)}  (xem: python -m calforge angles \"{args.keyword}\")")
    for c in res.concepts:
        print(f"  ✔ concept: {c}")
    for a in res.failed:
        print(f"  ✘ {a}: concept chưa qua kiểm tra - xem concept_report.md")


def cmd_angles(args, cfg):
    from . import layout
    f = layout.angles_file(products.root(cfg["projects_dir"]) / slugify(args.keyword))
    if not f.exists():
        sys.exit("Chưa có góc nào cho keyword này - chạy ideate trước.")
    for a in json.loads(f.read_text(encoding="utf-8")):
        feas = a["ai_feasibility"]["score"]
        print(f"{a['id']:>6}  [{a['frame_type']:<20}] [{a.get('style_family', '?'):<24}] AI {feas}/5 "
              f"{a['title']}")
        print(f"        {a['hook']}")


def cmd_import_angles(args, cfg):
    from .ideation.extract import extract_json
    from .ideation.pipeline import import_angles

    data = extract_json(Path(args.file).read_text(encoding="utf-8"))
    new, errors, warnings = import_angles(args.keyword, data, Path(cfg["projects_dir"]), args.source,
                                         keyword_root=products.root(cfg["projects_dir"]))
    for e in errors:
        print("LỖI    ", e)
    for w in warnings:
        print("CẢNH BÁO", w)
    if errors:
        print(f"Không nhập: {len(errors)} lỗi (sửa file hoặc nhờ AI sửa theo danh sách trên).")
        return
    for a in new:
        print(f"  + {a['id']:>6} [{a['style_family']:<20}] AI {a['ai_feasibility']['score']}/5  {a['title']}")
    print(f'Làm concept: python -m calforge ideate "{args.keyword}" --pick {new[0]["id"]}')


def cmd_check(args, cfg):
    d = _concept_dir(args.concept)
    c = json.loads(layout.concept_file(d).read_text(encoding="utf-8"))
    errors, warnings = validate_concept(c, c.get("year", cfg["year"]), c.get("market", cfg["market"]))
    for e in errors:
        print("LỖI    ", e)
    for w in warnings:
        print("CẢNH BÁO", w)
    print("Đạt." if not errors else f"{len(errors)} lỗi.")


def cmd_plan(args, cfg):
    d = _concept_dir(args.concept)
    jobs = plan.write_plan(d)
    csv_path = plan.export_csv(d)
    pending = [j["id"] for j in jobs if j["status"] == "pending"]
    print(f"{len(jobs)} job, còn {len(pending)}: {', '.join(pending) or '-'}")
    print(f"jobs.json: {layout.tech(d, 'jobs.json')}")
    print(f"CSV cho chatgpt-automation (trang /csv): {csv_path}")


def cmd_import(args, cfg):
    d = _concept_dir(args.concept)
    if not cfg.get("chatgpt_automation_dir"):
        sys.exit('Lệnh import cần "chatgpt_automation_dir" trong calforge.json (thư mục chatgpt-automation).')
    got = plan.import_from_automation(d, Path(cfg["chatgpt_automation_dir"]))
    print(f"Nhận {len(got)} ảnh: {', '.join(got) or '-'}")
    plan.write_plan(d)


def cmd_render(args, cfg):
    from .render.build import render_concept

    d = _concept_dir(args.concept)
    months = [int(x) for x in args.months.split(",")] if args.months else None
    res = render_concept(d, months, Path(args.placeholder_art) if args.placeholder_art else None)
    print(f"{len(res['pages'])} trang -> {res['out']}")
    for n in res["art"]:
        print("  ảnh:", n)
    for f in res["font_fallbacks"]:
        print("  font dự phòng:", f)
    print(f"Preflight: {len(res['issues'])} vấn đề" + ("" if not res["issues"] else ":"))
    for i in res["issues"]:
        print("  -", i)


def _print_status(rows):
    for r in rows:
        mark = "✔" if r.get("ok") else "✘"
        print(f"{mark} {Path(r['concept']).name}: bước {r.get('stage')} "
              f"{r.get('reason') or r.get('note') or ''}".rstrip())
        if r.get("product_id"):
            print(f"    Printify product: {r['product_id']}" + (" (đã publish)" if r.get("published") else " (NHÁP)"))


def cmd_run(args, cfg):
    from .pipeline import run

    if args.profiles:
        cfg["imagegen"]["profiles"] = args.profiles.split(",")

    rows = run(args.keyword, cfg, pick=args.pick.split(",") if args.pick else None, auto_pick=args.auto,
               printify=not args.no_printify, publish=args.publish, grid_preset=args.grid_preset,
               family=args.family, product=args.product, grid_mode=args.grid_mode, resume=args.resume,
               mockup_mode=args.mockup_mode)
    _print_status(rows)


def cmd_produce(args, cfg):
    from .pipeline import produce

    if args.profiles:
        cfg["imagegen"]["profiles"] = args.profiles.split(",")

    st = produce(_concept_dir(args.concept), cfg, printify=not args.no_printify, publish=args.publish)
    _print_status([{"concept": args.concept, **st}])
    if not st.get("ok"):
        sys.exit(1)


def cmd_finish(args, cfg):
    """Hoàn thiện một cuốn đã vẽ đủ tranh (không cần ChatGPT): upscale, trang in, PDF, ảnh quảng cáo, listing."""
    from .pipeline import finish_book, upscale_concept, _read_status

    d = _concept_dir(args.concept)
    if _read_status(d).get("terminal"):
        sys.exit("Cuốn đã bị loại (TM/bản quyền, nội dung nhạy cảm hoặc vi phạm chính sách), không hoàn thiện lại.")
    if args.redo_previews:
        for f in layout.listing(d).glob("*.jpg"):
            f.unlink()
        print("↻ Làm lại 5 ảnh quảng cáo")
    upscale_concept(d)
    st = finish_book(d, cfg, printify=False)
    _print_status([{"concept": args.concept, **st}])
    if not st.get("ok"):
        sys.exit(1)


def cmd_redo(args, cfg):
    from .pipeline import produce, redo_pages

    d = _concept_dir(args.concept)
    try:
        redo_pages(d, [p.strip() for p in args.pages.split(",") if p.strip()])
    except ValueError as e:
        sys.exit(f"✘ {e}")
    st = produce(d, cfg, printify=False)
    _print_status([{"concept": args.concept, **st}])
    if not st.get("ok"):
        sys.exit(1)


def cmd_gen(args, cfg):
    from .imagegen.generate import generate_concept

    d = _concept_dir(args.concept)
    plan.write_plan(d)
    ig = cfg["imagegen"]
    res = generate_concept(d, config.get_profiles_dir(cfg),
                           args.profiles.split(",") if args.profiles else ig.get("profiles"),
                           headless=ig.get("headless", False), timeout_s=ig.get("timeout_s", 420),
                           max_attempts=ig.get("max_attempts", 3))
    print("Thiếu:", ", ".join(res["missing"]) or "không")
    print("Lệch màu cần xem:", ", ".join(res["drift_flags"]) or "không", f"(chi tiết: {layout.tech(d, 'qc.md')})")


def cmd_upscale(args, cfg):
    from .pipeline import upscale_concept

    upscale_concept(_concept_dir(args.concept))


def cmd_listing(args, cfg):
    from .publish.listing import write_listing

    d = _concept_dir(args.concept)
    lst = write_listing(d)
    print(lst["title"])
    print("tags:", ", ".join(lst["tags"]))


def cmd_printify(args, cfg):
    from .publish.printify import create_product

    st = create_product(_concept_dir(args.concept), cfg, publish=args.publish)
    print("product:", st.get("product_id"), "(đã publish)" if st.get("published") else "(NHÁP)")


def cmd_shop(args, cfg):
    from .publish.r2 import R2Error
    if args.format == "calendaria":
        from .publish.calendaria_csv import publish_all
    else:
        from .publish.shop_csv import publish_all

    try:
        only = [Path(b) for b in args.book] if args.book else None
        res = publish_all(cfg, only=only)
    except R2Error as e:
        sys.exit(f"✘ {e}")
    print(f"Đã đẩy lên R2: {len(res['pushed'])} cuốn · xuất CSV: {len(res['exported'])} cuốn "
          f"(trong {res['books']} cuốn đã xong)")
    for f in res["failed"]:
        print(f"✘ {f}")
    print(f"CSV: {res['csv']}" if res["csv"] else "CSV: không có cuốn mới cần xuất")


def cmd_rename_sku(args, cfg):
    from .publish.shop_csv import shop_settings
    from .sku_rename import rename_all
    done = rename_all(Path(cfg["projects_dir"]), shop=shop_settings(cfg))
    print(f"Đã đổi tên {len(done)} cuốn sang SKU" if done else "Không còn cuốn nào cần đổi tên")


def cmd_ui(args, cfg):
    from .ui.server import run_server

    run_server(host=args.host, port=args.port, open_browser=not args.no_browser)


def cmd_accounts(args, cfg):
    from .llm import accounts

    if getattr(args, "delete", None):
        try:
            accounts.delete_account(args.delete, cfg)
            print(f"\n✔ Đã xóa tài khoản '{args.delete}' và thư mục profile trên ổ đĩa thành công.\n")
        except Exception as e:
            print(f"\n❌ Lỗi: {e}\n")
        return

    accs = accounts.list_accounts(cfg)
    pdir = accounts.get_profiles_dir(cfg)
    print(f"\n📁 Thư mục profiles: {pdir}")
    print(f"👥 Tổng số tài khoản: {len(accs)}\n")
    print(f"{'Tài khoản':<15} {'Trạng thái':<22} {'Lượt dùng':<12} {'Sửa đổi'}")
    print("-" * 65)
    for a in accs:
        status = "Đang mở 🔒" if a["is_locked"] else ("Đã có session ✔" if a["has_session"] else "Chưa có session")
        last = " (dùng gần nhất)" if a["is_last_used"] else ""
        print(f"{a['name']:<15} {status:<22} {str(a['use_count']) + last:<12} {a['modified_at']}")
    print("-" * 65)
    print("👉 Mở trình duyệt đăng nhập: python -m calforge login <tên_tài_khoản>\n")


def cmd_login(args, cfg):
    from .llm import accounts

    try:
        if not accounts.open_login_browser(args.profile, cfg):
            sys.exit(1)
    except KeyboardInterrupt:
        print("\nĐã hủy đăng nhập.")
    except Exception as e:  # noqa: BLE001 - hiện thông báo gọn thay vì traceback (UI đọc stdout)
        print(f"\n❌ Không mở được đăng nhập cho '{args.profile}': {e}")
        sys.exit(1)


def main(argv=None):
    cfg = config.load()
    ap = argparse.ArgumentParser(prog="calforge", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("facts")
    p.add_argument("--year", type=int)
    p.add_argument("--market")
    p.set_defaults(func=cmd_facts)

    p = sub.add_parser("ideate")
    p.add_argument("keyword")
    p.add_argument("--pick", help="id góc cụ thể, cách nhau bởi dấu phẩy (vd r1a2,r1a4)")
    p.add_argument("--auto", type=int, help="tự chọn N góc tốt nhất (mặc định theo config)")
    p.add_argument("--more", action="store_true", help="sinh thêm lượt góc mới, không trùng góc cũ")
    p.add_argument("--style", help="ép phong cách, bỏ qua gợi ý của ChatGPT")
    p.add_argument("--family", help="ép style đã duyệt: styled_photography, papercut_collage, mid_century_retro hoặc anime_illustration")
    p.add_argument("--grid-preset", default="auto",
                   choices=("auto", "bento_planner", "quiet_luxury", "soft_tech", "fresh_monochrome", "organic_capsules", "playful_editorial"),
                   help="tự chọn grid theo concept hoặc ép một preset")
    p.add_argument("--manual", action="store_true", help="dán prompt tay thay vì điều khiển Chrome")
    p.add_argument("--year", type=int)
    p.add_argument("--market")
    p.set_defaults(func=cmd_ideate)

    p = sub.add_parser("angles")
    p.add_argument("keyword")
    p.set_defaults(func=cmd_angles)

    p = sub.add_parser("import-angles", help="nhập góc tiếp cận do AI khác (vd Gemini) nghĩ ra")
    p.add_argument("keyword")
    p.add_argument("file", help="file chứa JSON góc tiếp cận (có thể còn chữ xung quanh)")
    p.add_argument("--source", default="gemini")
    p.set_defaults(func=cmd_import_angles)

    for name, fn in (("check", cmd_check), ("plan", cmd_plan), ("import", cmd_import)):
        p = sub.add_parser(name)
        p.add_argument("concept", help="thư mục chứa concept.json")
        p.set_defaults(func=fn)

    p = sub.add_parser("render")
    p.add_argument("concept", help="thư mục chứa concept.json")
    p.add_argument("--months", help="vd 1,3 (mặc định cả 12 tháng)")
    p.add_argument("--placeholder-art", help="ảnh tạm dùng khi tháng chưa có ảnh gen")
    p.set_defaults(func=cmd_render)

    p = sub.add_parser("run", help="keyword -> sản phẩm (trọn gói)")
    p.add_argument("--profiles", help="tài khoản gen ảnh, vd acc2,acc3,acc4,acc5")
    p.add_argument("keyword")
    p.add_argument("--pick")
    p.add_argument("--auto", type=int)
    p.add_argument("--family", choices=("styled_photography", "papercut_collage", "mid_century_retro", "anime_illustration"),
                   help="ép medium sản xuất cho toàn bộ dự án")
    p.add_argument("--grid-preset", default="auto",
                   choices=("auto", "bento_planner", "quiet_luxury", "soft_tech", "fresh_monochrome", "organic_capsules", "playful_editorial"))
    p.add_argument("--product", default="wall_grid", choices=("wall_grid", "wall_premade"),
                   help="loại lịch: wall_grid (máy thiết kế grid) hoặc wall_premade (grid in sẵn, không gen grid)")
    p.add_argument("--resume", action="store_true",
                   help="làm nốt batch trước của chủ đề này (chỉ các cuốn thiếu/hỏng), không mở batch mới")
    p.add_argument("--mockup-mode", choices=("template", "ai"),
                   help='chỉ với --grid-mode ai_page: template = mockup có sẵn; ai = AI gen bối cảnh cho 5 ảnh quảng cáo')
    p.add_argument("--grid-mode", choices=("ai_page", "background"),
                   help="Wall Calendar (Blank): ai_page = AI vẽ cả trang lịch; background = AI vẽ nền, code in lịch")
    p.add_argument("--no-printify", action="store_true", help="dừng ở file in + listing")
    p.add_argument("--publish", action="store_true", help="publish sang cửa hàng (mặc định chỉ tạo NHÁP)")
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("produce", help="concept có sẵn -> sản phẩm")
    p.add_argument("--profiles", help="tài khoản gen ảnh, vd acc2,acc3,acc4,acc5")
    p.add_argument("concept")
    p.add_argument("--no-printify", action="store_true")
    p.add_argument("--publish", action="store_true")
    p.set_defaults(func=cmd_produce)

    p = sub.add_parser("finish", help="hoàn thiện cuốn đã vẽ đủ tranh: trang in, PDF, ảnh quảng cáo, listing")
    p.add_argument("concept")
    p.add_argument("--redo-previews", action="store_true", help="xoá và làm lại 5 ảnh quảng cáo")
    p.set_defaults(func=cmd_finish)

    p = sub.add_parser("redo", help="vẽ lại vài trang hỏng của một cuốn rồi làm lại các bước sau")
    p.add_argument("concept")
    p.add_argument("--pages", required=True, help="vd cover,m05,grid")
    p.set_defaults(func=cmd_redo)

    p = sub.add_parser("gen", help="gen ảnh cho concept (ảnh neo trước, còn lại song song)")
    p.add_argument("concept")
    p.add_argument("--profiles", help="vd acc2,acc3 (mặc định: mọi profile)")
    p.set_defaults(func=cmd_gen)

    for name, fn in (("upscale", cmd_upscale), ("listing", cmd_listing)):
        p = sub.add_parser(name)
        p.add_argument("concept")
        p.set_defaults(func=fn)

    p = sub.add_parser("printify", help="upload + tạo sản phẩm NHÁP trên Printify")
    p.add_argument("concept")
    p.add_argument("--publish", action="store_true")
    p.set_defaults(func=cmd_printify)

    p = sub.add_parser("shop", help="đẩy các cuốn đã xong lên R2 + xuất CSV sản phẩm cho cuốn chưa xuất")
    p.add_argument("--book", action="append", help="chỉ cuốn này (thư mục cuốn, lặp lại được); bỏ trống = mọi cuốn")
    p.add_argument("--format", choices=("printify", "calendaria"), default="printify", help="mẫu CSV cần xuất")
    p.set_defaults(func=cmd_shop)

    p = sub.add_parser("rename-sku", help="đổi tên thư mục các cuốn cũ sang mã SKU (giữ SKU đã xuất)")
    p.set_defaults(func=cmd_rename_sku)

    p = sub.add_parser("ui", help="mở giao diện web CalForge Studio")
    p.add_argument("--port", type=int, default=8080, help="cổng mạng (mặc định 8080)")
    p.add_argument("--host", default="127.0.0.1", help="host lắng nghe (mặc định 127.0.0.1)")
    p.add_argument("--no-browser", action="store_true", help="không tự động mở trình duyệt")
    p.set_defaults(func=cmd_ui)

    p = sub.add_parser("accounts", help="liệt kê danh sách tài khoản ChatGPT")
    p.add_argument("--delete", help="xóa tài khoản và thư mục profile trên ổ đĩa (vd: --delete test_acc)")
    p.set_defaults(func=cmd_accounts)

    p = sub.add_parser("login", help="mở trình duyệt Chrome để đăng nhập tài khoản ChatGPT")
    p.add_argument("profile", help="tên tài khoản/profile (vd acc1, acc6)")
    p.set_defaults(func=cmd_login)

    args = ap.parse_args(argv)
    args.func(args, cfg)


if __name__ == "__main__":
    main()
