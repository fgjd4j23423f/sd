# this scripts installs necessary requirements and launches main program in webui.py
import subprocess
import os
import sys
import importlib.util
import platform
import json
from functools import lru_cache
import threading

from modules import cmd_args
from modules.paths_internal import script_path, extensions_dir

args, _ = cmd_args.parser.parse_known_args()

python = sys.executable
git = os.environ.get('GIT', "git")
index_url = os.environ.get('INDEX_URL', "")
dir_repos = "repositories"

# Whether to default to printing command output
default_command_live = (os.environ.get('WEBUI_LAUNCH_LIVE_OUTPUT') == "1")

if 'GRADIO_ANALYTICS_ENABLED' not in os.environ:
    os.environ['GRADIO_ANALYTICS_ENABLED'] = 'False'


def check_python_version():
    is_windows = platform.system() == "Windows"
    major = sys.version_info.major
    minor = sys.version_info.minor
    micro = sys.version_info.micro

    if is_windows:
        supported_minors = [10]
    else:
        supported_minors = [7, 8, 9, 10, 11]

    if not (major == 3 and minor in supported_minors):
        import modules.errors

        modules.errors.print_error_explanation(f"""
INCOMPATIBLE PYTHON VERSION

This program is tested with 3.10.6 Python, but you have {major}.{minor}.{micro}.
If you encounter an error with "RuntimeError: Couldn't install torch." message,
or any other error regarding unsuccessful package (library) installation,
please downgrade (or upgrade) to the latest version of 3.10 Python
and delete current Python and "venv" folder in WebUI's directory.

You can download 3.10 Python from here: https://www.python.org/downloads/release/python-3106/

{"Alternatively, use a binary release of WebUI: https://github.com/AUTOMATIC1111/stable-diffusion-webui/releases" if is_windows else ""}

Use --skip-python-version-check to suppress this warning.
""")


@lru_cache()
def commit_hash():
    try:
        return subprocess.check_output([git, "rev-parse", "HEAD"], shell=False, encoding='utf8').strip()
    except Exception:
        return "<none>"


@lru_cache()
def git_tag():
    try:
        return subprocess.check_output([git, "describe", "--tags"], shell=False, encoding='utf8').strip()
    except Exception:
        return "<none>"


def run(command, desc=None, errdesc=None, custom_env=None, live: bool = default_command_live) -> str:
    if desc is not None:
        print(desc)

    run_kwargs = {
        "args": command,
        "shell": True,
        "env": os.environ if custom_env is None else custom_env,
        "encoding": 'utf8',
        "errors": 'ignore',
    }

    if not live:
        run_kwargs["stdout"] = run_kwargs["stderr"] = subprocess.PIPE

    result = subprocess.run(**run_kwargs)

    if result.returncode != 0:
        error_bits = [
            f"{errdesc or 'Error running command'}.",
            f"Command: {command}",
            f"Error code: {result.returncode}",
        ]
        if result.stdout:
            error_bits.append(f"stdout: {result.stdout}")
        if result.stderr:
            error_bits.append(f"stderr: {result.stderr}")
        raise RuntimeError("\n".join(error_bits))

    return (result.stdout or "")


def is_installed(package):
    try:
        spec = importlib.util.find_spec(package)
    except ModuleNotFoundError:
        return False

    return spec is not None


def repo_dir(name):
    return os.path.join(script_path, dir_repos, name)


def run_pip(command, desc=None, live=default_command_live):
    if args.skip_install:
        return

    index_url_line = f' --index-url {index_url}' if index_url != '' else ''
    return run(f'"{python}" -m pip {command} --prefer-binary{index_url_line}', desc=f"Installing {desc}",
               errdesc=f"Couldn't install {desc}", live=live)


def check_run_python(code: str) -> bool:
    result = subprocess.run([python, "-c", code], capture_output=True, shell=False)
    return result.returncode == 0


def git_clone(url, dir, name, commithash=None):
    # TODO clone into temporary dir and move if successful

    if os.path.exists(dir):
        if commithash is None:
            return

        current_hash = run(f'"{git}" -C "{dir}" rev-parse HEAD', None,
                           f"Couldn't determine {name}'s hash: {commithash}").strip()
        if current_hash == commithash:
            return

        run(f'"{git}" -C "{dir}" fetch', f"Fetching updates for {name}...", f"Couldn't fetch {name}")
        run(f'"{git}" -C "{dir}" checkout {commithash}', f"Checking out commit for {name} with hash: {commithash}...",
            f"Couldn't checkout commit {commithash} for {name}")
        return

    run(f'"{git}" clone "{url}" "{dir}"', f"Cloning {name} into {dir}...", f"Couldn't clone {name}")

    if commithash is not None:
        run(f'"{git}" -C "{dir}" checkout {commithash}', None, "Couldn't checkout {name}'s hash: {commithash}")


def git_pull_recursive(dir):
    for subdir, _, _ in os.walk(dir):
        if os.path.exists(os.path.join(subdir, '.git')):
            try:
                output = subprocess.check_output([git, '-C', subdir, 'pull', '--autostash'])
                print(f"Pulled changes for repository in '{subdir}':\n{output.decode('utf-8').strip()}\n")
            except subprocess.CalledProcessError as e:
                print(f"Couldn't perform 'git pull' on repository in '{subdir}':\n{e.output.decode('utf-8').strip()}\n")


def version_check(commit):
    try:
        import requests
        commits = requests.get(
            'https://api.github.com/repos/AUTOMATIC1111/stable-diffusion-webui/branches/master').json()
        if commit != "<none>" and commits['commit']['sha'] != commit:
            print("--------------------------------------------------------")
            print("| You are not up to date with the most recent release. |")
            print("| Consider running `git pull` to update.               |")
            print("--------------------------------------------------------")
        elif commits['commit']['sha'] == commit:
            print("You are up to date with the most recent release.")
        else:
            print("Not a git clone, can't perform version check.")
    except Exception as e:
        print("version check failed", e)


def run_extension_installer(extension_dir):
    path_installer = os.path.join(extension_dir, "install.py")
    if not os.path.isfile(path_installer):
        return

    try:
        env = os.environ.copy()
        env['PYTHONPATH'] = os.path.abspath(".")

        print(run(f'"{python}" "{path_installer}"', errdesc=f"Error running install.py for extension {extension_dir}",
                  custom_env=env))
    except Exception as e:
        print(e, file=sys.stderr)


def list_extensions(settings_file):
    settings = {}

    try:
        if os.path.isfile(settings_file):
            with open(settings_file, "r", encoding="utf8") as file:
                settings = json.load(file)
    except Exception as e:
        print(e, file=sys.stderr)

    disabled_extensions = set(settings.get('disabled_extensions', []))
    disable_all_extensions = settings.get('disable_all_extensions', 'none')

    if disable_all_extensions != 'none':
        return []

    return [x for x in os.listdir(extensions_dir) if x not in disabled_extensions]


def run_extensions_installers(settings_file):
    if not os.path.isdir(extensions_dir):
        return

    for dirname_extension in list_extensions(settings_file):
        run_extension_installer(os.path.join(extensions_dir, dirname_extension))


def prepare_environment():
    requirements_file = os.environ.get('REQS_FILE', "requirements_versions.txt")

    xformers_package = os.environ.get('XFORMERS_PACKAGE', 'xformers==0.0.17')
    gfpgan_package = os.environ.get('GFPGAN_PACKAGE',
                                    "https://github.com/TencentARC/GFPGAN/archive/8d2447a2d918f8eba5a4a01463fd48e45126a379.zip")
    clip_package = os.environ.get('CLIP_PACKAGE',
                                  "https://github.com/openai/CLIP/archive/d50d76daa670286dd6cacf3bcd80b5e4823fc8e1.zip")
    openclip_package = os.environ.get('OPENCLIP_PACKAGE',
                                      "https://github.com/mlfoundations/open_clip/archive/bb6e834e9c70d9c27d0dc3ecedeebeaeb1ffad6b.zip")

    stable_diffusion_repo = os.environ.get('STABLE_DIFFUSION_REPO',
                                           "https://github.com/Stability-AI/stablediffusion.git")
    taming_transformers_repo = os.environ.get('TAMING_TRANSFORMERS_REPO',
                                              "https://github.com/CompVis/taming-transformers.git")
    k_diffusion_repo = os.environ.get('K_DIFFUSION_REPO', 'https://github.com/crowsonkb/k-diffusion.git')
    blip_repo = os.environ.get('BLIP_REPO', 'https://github.com/salesforce/BLIP.git')

    stable_diffusion_commit_hash = os.environ.get('STABLE_DIFFUSION_COMMIT_HASH',
                                                  "cf1d67a6fd5ea1aa600c4df58e5b47da45f6bdbf")
    taming_transformers_commit_hash = os.environ.get('TAMING_TRANSFORMERS_COMMIT_HASH',
                                                     "24268930bf1dce879235a7fddd0b2355b84d7ea6")
    k_diffusion_commit_hash = os.environ.get('K_DIFFUSION_COMMIT_HASH', "c9fe758757e022f05ca5a53fa8fac28889e4f1cf")
    blip_commit_hash = os.environ.get('BLIP_COMMIT_HASH', "48211a1594f1321b00f14c9f7a5b4813144b2fb9")

    if not args.skip_python_version_check:
        check_python_version()

    commit = commit_hash()
    tag = git_tag()

    print(f"Python {sys.version}")
    print(f"Version: {tag}")
    print(f"Commit hash: {commit}")

    os.makedirs(dir_repos, exist_ok=True)

    if not os.path.exists('/tmp/gradio'):
        os.makedirs('/tmp/gradio')

    def task_install_gfpgan():
        if not is_installed("gfpgan"):
            run_pip(f"install {gfpgan_package}", "gfpgan")

    def task_install_clip():
        if not is_installed("clip"):
            run_pip(f"install {clip_package}", "clip")

    def task_install_open_clip():
        if not is_installed("open_clip"):
            run_pip(f"install {openclip_package}", "open_clip")

    def task_clone_stable_diffusion_repo():
        git_clone(stable_diffusion_repo, repo_dir('stable-diffusion-stability-ai'), "Stable Diffusion",
                  stable_diffusion_commit_hash)

    def task_clone_repos():
        git_clone(taming_transformers_repo, repo_dir('taming-transformers'), "Taming Transformers",
                  taming_transformers_commit_hash)
        git_clone(k_diffusion_repo, repo_dir('k-diffusion'), "K-diffusion", k_diffusion_commit_hash)
        git_clone(blip_repo, repo_dir('BLIP'), "BLIP", blip_commit_hash)

    def task_install_webui_requirements():
        run_pip(f"install -r {requirements_file}", "requirements for Web UI")

    def task_download_lora():
        import subprocess
        subprocess.run(
            'git lfs install && git clone --depth 1 --jobs 3 https://huggingface.co/zoto-ff/Lora /content/sd/models/Lora --quiet > /dev/null',
            shell=True)

    try:
        tasks = [
            task_install_gfpgan,
            task_install_clip,
            task_install_open_clip,
            task_clone_stable_diffusion_repo,
            task_clone_repos,
            task_download_lora
        ]

        t = []
        for task in tasks:
            task = threading.Thread(target=task)
            task.start()
            t.append(task)

        for task in t:
            task.join()

        task_install_webui_requirements()

        ddimpy_path = 'repositories/stable-diffusion-stability-ai/ldm/models/diffusion/ddim.py'
        os.system('perl -pi -e "s/print\(f\'Data shape/#/g" ' + ddimpy_path)
        os.system('perl -pi -e "s/print\(f\\"Running DDIM/#/g" ' + ddimpy_path)
    except RuntimeError:
        print('похуй')
    except Exception as e:
        print(e)


def configure_for_tests():
    if "--api" not in sys.argv:
        sys.argv.append("--api")
    if "--ckpt" not in sys.argv:
        sys.argv.append("--ckpt")
        sys.argv.append(os.path.join(script_path, "test/test_files/empty.pt"))
    if "--skip-torch-cuda-test" not in sys.argv:
        sys.argv.append("--skip-torch-cuda-test")
    if "--disable-nan-check" not in sys.argv:
        sys.argv.append("--disable-nan-check")

    os.environ['COMMANDLINE_ARGS'] = ""


def start():
    print(f"Launching {'API server' if '--nowebui' in sys.argv else 'Web UI'} with arguments: {' '.join(sys.argv[1:])}")
    import webui
    if '--nowebui' in sys.argv:
        webui.api_only()
    else:
        webui.webui()
