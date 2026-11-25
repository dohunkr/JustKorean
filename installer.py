"""One-click GUI & CLI installer for Just Volleyball Korean Patch."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import Callable, Dict, Optional

from patch_engine import (
    patch_fontdata,
    patch_gdc,
    patch_res_text,
    patch_scn_variants,
    rebuild_pck,
)

GAME_FOLDER_NAME = "just volleyball"
PCK_NAME = "volleyball.pck"
BACKUP_NAME = "volleyball.pck.bak"
EXP_PREFIX = ".godot/exported/133200997/"
FONT_DIR_PREFIX = ".godot/imported/"

FONT_MAP = {
    "Nunito-Black.ttf-077e13a2ecb56ab8add1ca111f8fab9f.fontdata": "Pretendard-Black.otf",
    "Nunito-Bold.ttf-9cfedcbcab5128a7c167e8d6c3f0b818.fontdata": "Pretendard-Bold.otf",
    "Nunito-ExtraBold.ttf-7a746dae6e99962a06984cca79747dcd.fontdata": "Pretendard-ExtraBold.otf",
    "Nunito-SemiBold.ttf-967b3762826f2d4e3d6c6109f4f6048f.fontdata": "Pretendard-SemiBold.otf",
    "Nunito-SemiBoldItalic.ttf-5b0c9df7a795442bb5f4d5ecb80ce1dc.fontdata": "Pretendard-SemiBold.otf",
    "PublicPixel.ttf-e7881b9d989caaa462513f59362f0ce3.fontdata": "Galmuri9.ttf",
    "VarsityTeam-Bold.otf-6e3a4f96f8c9bf766e5d56f0d8d84534.fontdata": "Pretendard-Black.otf",
}


def resource_base_dir() -> str:
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return sys._MEIPASS  # type: ignore[attr-defined]
    return os.path.dirname(os.path.abspath(__file__))


def find_game_dir() -> Optional[str]:
    candidates = [
        r"C:\Program Files (x86)\Steam\steamapps\common\just volleyball",
        r"C:\Program Files\Steam\steamapps\common\just volleyball",
        r"D:\SteamLibrary\steamapps\common\just volleyball",
        r"E:\SteamLibrary\steamapps\common\just volleyball",
        r"F:\SteamLibrary\steamapps\common\just volleyball",
    ]
    # Parse Steam libraryfolders.vdf if available
    vdf_paths = [
        r"C:\Program Files (x86)\Steam\steamapps\libraryfolders.vdf",
        r"C:\Program Files\Steam\steamapps\libraryfolders.vdf",
    ]
    for vdf in vdf_paths:
        if os.path.isfile(vdf):
            try:
                text = open(vdf, "r", encoding="utf-8", errors="ignore").read()
                for line in text.splitlines():
                    if '"path"' in line:
                        parts = line.split('"')
                        if len(parts) >= 4:
                            lib_path = parts[3].replace("\\\\", "\\")
                            candidates.insert(
                                0, os.path.join(lib_path, "steamapps", "common", GAME_FOLDER_NAME)
                            )
            except OSError:
                pass

    for c in candidates:
        if os.path.isfile(os.path.join(c, PCK_NAME)):
            return c
    return None


def build_patch_map(patch_data_dir: str) -> Dict[str, Callable[[bytes], bytes]]:
    patch_map: Dict[str, Callable[[bytes], bytes]] = {}

    # 1. Fonts
    fonts_dir = os.path.join(patch_data_dir, "fonts")
    font_cache: Dict[str, bytes] = {}
    for fd_name, target_font in FONT_MAP.items():
        if target_font not in font_cache:
            fpath = os.path.join(fonts_dir, target_font)
            if not os.path.isfile(fpath):
                # fallback between .otf and .ttf
                alt = target_font[:-4] + (".ttf" if target_font.endswith(".otf") else ".otf")
                fpath = os.path.join(fonts_dir, alt)
            font_cache[target_font] = open(fpath, "rb").read()
        ttf_bytes = font_cache[target_font]
        patch_map[FONT_DIR_PREFIX + fd_name] = (
            lambda raw, b=ttf_bytes: patch_fontdata(raw, b)
        )

    # 2. JSON files
    how_to_path = os.path.join(patch_data_dir, "how_to_text.ko.json")
    if os.path.isfile(how_to_path):
        how_to_bytes = open(how_to_path, "rb").read()
        patch_map["game/ui/how_to_text.json"] = lambda _raw, b=how_to_bytes: b

    chat_swaps_path = os.path.join(patch_data_dir, "chat_swaps.ko.json")
    if os.path.isfile(chat_swaps_path):
        chat_bytes = open(chat_swaps_path, "rb").read()
        patch_map["game/net/chat_swaps.json"] = lambda _raw, b=chat_bytes: b

    # 3. .scn files
    scn_path = os.path.join(patch_data_dir, "translations_scn.json")
    if os.path.isfile(scn_path):
        scn_data = json.load(open(scn_path, "r", encoding="utf-8"))
        for fn, rep in scn_data.items():
            if rep:
                patch_map[EXP_PREFIX + fn] = (
                    lambda raw, r=rep: patch_scn_variants(raw, r)
                )

    # 4. .res files
    res_path = os.path.join(patch_data_dir, "translations_res.json")
    if os.path.isfile(res_path):
        res_data = json.load(open(res_path, "r", encoding="utf-8"))
        for fn, info in res_data.items():
            prop = info["prop"]
            ko = info["ko"]
            patch_map[EXP_PREFIX + fn] = (
                lambda raw, p=prop, k=ko: patch_res_text(raw, p, k)
            )

    # 5. .gdc files
    gdc_path = os.path.join(patch_data_dir, "translations_gdc.json")
    if os.path.isfile(gdc_path):
        gdc_data = json.load(open(gdc_path, "r", encoding="utf-8"))
        for rel, rep in gdc_data.items():
            if rep:
                patch_map[rel] = lambda raw, r=rep: patch_gdc(raw, r)

    return patch_map


def install_patch(
    game_dir: str,
    progress_cb: Optional[Callable[[int, int, str], None]] = None,
) -> None:
    pck_path = os.path.join(game_dir, PCK_NAME)
    bak_path = os.path.join(game_dir, BACKUP_NAME)
    tmp_path = os.path.join(game_dir, PCK_NAME + ".tmp")

    if not os.path.isfile(pck_path):
        raise FileNotFoundError(f"{PCK_NAME} 파일을 찾을 수 없습니다: {game_dir}")

    if not os.path.isfile(bak_path):
        if progress_cb:
            progress_cb(0, 100, "원본 volleyball.pck 백업 생성 중...")
        shutil.copy2(pck_path, bak_path)

    patch_data_dir = os.path.join(resource_base_dir(), "patch_data")
    patch_map = build_patch_map(patch_data_dir)
    rebuild_pck(bak_path, tmp_path, patch_map, progress_cb=progress_cb)
    os.replace(tmp_path, pck_path)


def restore_backup(game_dir: str) -> None:
    pck_path = os.path.join(game_dir, PCK_NAME)
    bak_path = os.path.join(game_dir, BACKUP_NAME)
    if not os.path.isfile(bak_path):
        raise FileNotFoundError("백업 파일(volleyball.pck.bak)이 없습니다.")
    shutil.copy2(bak_path, pck_path)


class InstallerApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("Just Volleyball 한글 패치 설치기")
        self.root.geometry("540x290")
        self.root.resizable(False, False)

        detected = find_game_dir() or ""
        self.dir_var = tk.StringVar(value=detected)
        self.status_var = tk.StringVar(value="게임 폴더를 확인한 뒤 [한글 패치 설치]를 눌러주세요.")

        pad = {"padx": 16, "pady": 6}
        tk.Label(
            root,
            text="Just Volleyball 비공식 한글 패치",
            font=("맑은 고딕", 14, "bold"),
        ).pack(pady=(16, 4))
        tk.Label(
            root,
            text="원클릭 설치기 · 원본 자동 백업 및 복원 지원",
            font=("맑은 고딕", 9),
            fg="#555555",
        ).pack(pady=(0, 10))

        frame = tk.Frame(root)
        frame.pack(fill="x", **pad)
        tk.Label(frame, text="게임 폴더:", font=("맑은 고딕", 9)).pack(anchor="w")
        row = tk.Frame(frame)
        row.pack(fill="x", pady=(4, 0))
        self.entry = tk.Entry(row, textvariable=self.dir_var, font=("맑은 고딕", 9))
        self.entry.pack(side="left", fill="x", expand=True)
        tk.Button(row, text="찾아보기...", command=self.browse).pack(side="left", padx=(6, 0))

        self.progress = ttk.Progressbar(root, mode="determinate", maximum=100)
        self.progress.pack(fill="x", padx=16, pady=(12, 4))

        tk.Label(root, textvariable=self.status_var, font=("맑은 고딕", 9), fg="#333333").pack(
            padx=16, anchor="w"
        )

        btn_row = tk.Frame(root)
        btn_row.pack(pady=16)
        self.btn_install = tk.Button(
            btn_row,
            text="한글 패치 설치",
            width=18,
            height=2,
            bg="#1f6feb",
            fg="white",
            font=("맑은 고딕", 10, "bold"),
            command=self.on_install,
        )
        self.btn_install.pack(side="left", padx=8)
        self.btn_restore = tk.Button(
            btn_row,
            text="원본 복원 (제거)",
            width=18,
            height=2,
            font=("맑은 고딕", 10),
            command=self.on_restore,
        )
        self.btn_restore.pack(side="left", padx=8)

    def browse(self) -> None:
        chosen = filedialog.askdirectory(title="Just Volleyball 설치 폴더 선택")
        if chosen:
            self.dir_var.set(chosen)

    def _set_busy(self, busy: bool) -> None:
        state = "disabled" if busy else "normal"
        self.btn_install.config(state=state)
        self.btn_restore.config(state=state)

    def on_install(self) -> None:
        game_dir = self.dir_var.get().strip()
        if not os.path.isfile(os.path.join(game_dir, PCK_NAME)):
            messagebox.showerror("오류", "선택한 폴더에 volleyball.pck 파일이 없습니다.")
            return
        self._set_busy(True)

        def worker() -> None:
            try:
                def cb(cur: int, total: int, msg: str) -> None:
                    pct = int((cur / max(total, 1)) * 100)
                    self.root.after(0, lambda: self.progress.configure(value=pct))
                    self.root.after(0, lambda: self.status_var.set(f"패치 적용 중... ({pct}%) {msg}"))

                install_patch(game_dir, progress_cb=cb)
                self.root.after(0, lambda: self.progress.configure(value=100))
                self.root.after(0, lambda: self.status_var.set("한글 패치 설치가 완료되었습니다!"))
                self.root.after(
                    0,
                    lambda: messagebox.showinfo(
                        "완료", "한글 패치 설치가 완료되었습니다!\nSteam에서 게임을 실행해 주세요."
                    ),
                )
            except Exception as exc:
                self.root.after(0, lambda: self.status_var.set(f"오류: {exc}"))
                self.root.after(0, lambda: messagebox.showerror("설치 실패", str(exc)))
            finally:
                self.root.after(0, lambda: self._set_busy(False))

        threading.Thread(target=worker, daemon=True).start()

    def on_restore(self) -> None:
        game_dir = self.dir_var.get().strip()
        try:
            restore_backup(game_dir)
            self.status_var.set("원본 파일로 복원되었습니다.")
            messagebox.showinfo("완료", "원본 volleyball.pck 파일로 복원되었습니다.")
        except Exception as exc:
            messagebox.showerror("복원 실패", str(exc))


def main() -> None:
    parser = argparse.ArgumentParser(description="Just Volleyball Korean Patch Installer")
    parser.add_argument("--install", action="store_true", help="Install patch via CLI")
    parser.add_argument("--restore", action="store_true", help="Restore backup via CLI")
    parser.add_argument("--game-dir", type=str, default=None, help="Path to just volleyball folder")
    args = parser.parse_args()

    if args.install or args.restore:
        gdir = args.game_dir or find_game_dir()
        if not gdir:
            print("Error: Could not find just volleyball directory. Use --game-dir.", file=sys.stderr)
            sys.exit(1)
        if args.restore:
            restore_backup(gdir)
            print("Restored original volleyball.pck.")
        else:
            install_patch(
                gdir,
                progress_cb=lambda c, t, m: print(f"[{c}/{t}] {m}") if c == t or c % 1000 == 0 else None,
            )
            print("Installed Korean patch successfully.")
        return

    root = tk.Tk()
    InstallerApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
