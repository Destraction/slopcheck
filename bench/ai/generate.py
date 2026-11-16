"""Корпус ИИ-кода: рабочие копии заготовок и сбор патчей (v4, H1).

    uv run python bench/ai/generate.py prepare TASK MODEL   рабочая копия seed с git, печатает путь
    uv run python bench/ai/generate.py prompt TASK [DIR]    текст задачи для агента
    uv run python bench/ai/generate.py collect TASK MODEL   git diff рабочей копии → out/MODEL/TASK.patch
    uv run python bench/ai/generate.py gemini TASK          prepare + `gemini -p` + collect
    uv run python bench/ai/generate.py apply TASK MODEL DIR seed + патч в DIR (для замера полноты)

Рабочие копии — в ~/.cache/slopcheck-bench/ai/<model>/<task>, вне репозитория:
там нет `.slopcheck.yml`, и Stop-хук slopcheck не исправит slop до замера.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

import yaml

AI = Path(__file__).resolve().parent
SEEDS = AI / "seeds"
OUT = AI / "out"
WORK = Path.home() / ".cache" / "slopcheck-bench" / "ai"
# Lock-файлы и сумма модулей — шум для патча: их генерирует менеджер пакетов.
_PATCH_EXCLUDES = (":!package-lock.json", ":!pnpm-lock.yaml", ":!yarn.lock", ":!go.sum", ":!*.tsbuildinfo")
_GIT_ID = ("-c", "user.name=seed", "-c", "user.email=seed@localhost")


def load_tasks() -> dict[str, dict]:
    """Задачи из tasks.yml по id."""
    data = yaml.safe_load((AI / "tasks.yml").read_text(encoding="utf-8"))
    return {task["id"]: task for task in data["tasks"]}


def _git(cwd: Path, *args: str) -> str:
    """git в каталоге `cwd`; ошибка — исключение с выводом."""
    done = subprocess.run(["git", *_GIT_ID, *args], cwd=cwd, capture_output=True, text=True, check=True)
    return done.stdout


def _copy_seed(task: dict, dest: Path) -> None:
    """Скопировать заготовку задачи в `dest` (без node_modules)."""
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(SEEDS / task["seed"], dest, ignore=shutil.ignore_patterns("node_modules", "dist"))


def prepare(task_id: str, model: str) -> Path:
    """Чистая рабочая копия заготовки с коммитом seed."""
    task = load_tasks()[task_id]
    work = WORK / model / task_id
    _copy_seed(task, work)
    _git(work, "init", "-q")
    _git(work, "add", "-A")
    _git(work, "commit", "-q", "-m", "seed")
    return work


def prompt_for(task_id: str, work: Path | None = None) -> str:
    """Текст задачи так, как его написал бы пользователь."""
    text = " ".join(load_tasks()[task_id]["prompt"].split())
    if work is None:
        return text
    return f"Проект лежит в {work}. {text} Работай только в этой папке, коммитить не нужно."


def collect(task_id: str, model: str) -> Path:
    """Снять изменения агента патчем в out/<model>/<task>.patch."""
    work = WORK / model / task_id
    _git(work, "add", "-A")
    patch = _git(work, "diff", "--cached", "--binary", "HEAD", "--", ".", *_PATCH_EXCLUDES)
    if not patch.strip():
        raise SystemExit(f"{model}/{task_id}: агент ничего не изменил")
    dest = OUT / model / f"{task_id}.patch"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(patch, encoding="utf-8")
    return dest


def apply(task_id: str, model: str, dest: Path) -> Path:
    """Заготовка с наложенным патчем агента — для прогона slopcheck."""
    _copy_seed(load_tasks()[task_id], dest)
    patch = OUT / model / f"{task_id}.patch"
    subprocess.run(["git", "apply", "--whitespace=nowarn", str(patch)], cwd=dest, check=True)
    return dest


def gemini(task_id: str) -> Path:
    """Сгенерировать решение Gemini CLI в headless-режиме и собрать патч."""
    work = prepare(task_id, "gemini")
    subprocess.run(["gemini", "--yolo", "-p", prompt_for(task_id, work)], cwd=work, check=True)
    return collect(task_id, "gemini")


def main() -> None:
    """Разбор команд."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    for name in ("prepare", "collect"):
        cmd = sub.add_parser(name)
        cmd.add_argument("task")
        cmd.add_argument("model")
    cmd = sub.add_parser("prompt")
    cmd.add_argument("task")
    cmd.add_argument("dir", nargs="?")
    sub.add_parser("gemini").add_argument("task")
    cmd = sub.add_parser("apply")
    cmd.add_argument("task")
    cmd.add_argument("model")
    cmd.add_argument("dir")
    args = parser.parse_args()
    if args.cmd == "prepare":
        print(prepare(args.task, args.model))
    elif args.cmd == "prompt":
        print(prompt_for(args.task, Path(args.dir) if args.dir else None))
    elif args.cmd == "collect":
        print(collect(args.task, args.model))
    elif args.cmd == "gemini":
        print(gemini(args.task))
    else:
        print(apply(args.task, args.model, Path(args.dir)))


if __name__ == "__main__":
    sys.exit(main())
