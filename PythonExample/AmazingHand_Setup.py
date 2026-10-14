"""Setup notebook trên máy mới bằng đúng Python kernel hiện tại."""

from importlib import metadata, util
from pathlib import Path
import hashlib
import json
import subprocess
import sys
import urllib.request
import zipfile


def _pip_install(arguments):
    if util.find_spec('pip') is None:
        subprocess.check_call([sys.executable, '-m', 'ensurepip', '--upgrade'])
    subprocess.check_call([sys.executable, '-m', 'pip', 'install', *arguments])


def _requirements(path):
    """Các profile chỉ chứa requirement chuẩn và include -r tương đối."""
    from packaging.requirements import Requirement
    result = []
    for line in Path(path).read_text(encoding='utf-8').splitlines():
        line = line.split('#', 1)[0].strip()
        if not line:
            continue
        if line.startswith('-r '):
            result.extend(_requirements(Path(path).parent / line[3:].strip()))
        else:
            result.append(Requirement(line))
    return result


def ensure_dependencies(profile):
    """Cài package thiếu/sai phiên bản; chỉ yêu cầu restart nếu module đã load bị đổi."""
    if not (3, 11) <= sys.version_info[:2] < (3, 13):
        raise RuntimeError('Chọn Python 3.11–3.12 (khuyến nghị 3.12) làm kernel rồi chạy lại.')
    if util.find_spec('packaging') is None:
        _pip_install(['packaging>=24'])
    profile = Path(profile).resolve()
    requirements = _requirements(profile)
    missing = []
    for requirement in requirements:
        if requirement.marker and not requirement.marker.evaluate():
            continue
        try:
            installed = metadata.version(requirement.name)
        except metadata.PackageNotFoundError:
            installed = None
        if installed is None or not requirement.specifier.contains(installed, prereleases=True):
            missing.append(str(requirement))
    if missing:
        loaded = {dist for module, dists in metadata.packages_distributions().items()
                  if module in sys.modules for dist in dists}
        before = {name: metadata.version(name) for name in loaded}
        print('Cài vào kernel:', sys.executable, '\nPackage thiếu/sai phiên bản:', missing, flush=True)
        _pip_install([*missing, '--constraint', str(profile)])
        changed = [name for name, old in before.items() if metadata.version(name) != old]
        if changed:
            raise RuntimeError('Đã cập nhật package đang được kernel dùng: ' + ', '.join(changed)
                               + '. Restart Kernel, rồi chạy lại từ cell đầu.')
    print('PASS — Dependency đúng phiên bản; kernel:', sys.executable)


def choose_serial_port(preferred='auto'):
    """Ưu tiên adapter CH343 của bàn tay, không phụ thuộc số COM trên máy."""
    from serial.tools import list_ports
    ports = list(list_ports.comports())
    if preferred != 'auto':
        return preferred
    hand_ports = [p.device for p in ports if 'ch343' in ' '.join(str(getattr(p, key, '') or '')
                  for key in ('description', 'product', 'interface', 'hwid')).lower()]
    if len(hand_ports) == 1:
        print('PASS — Tự nhận adapter bàn tay CH343:', hand_ports[0])
        return hand_ports[0]
    if len(hand_ports) > 1:
        raise RuntimeError(f'Có nhiều adapter CH343: {hand_ports}. Chỉ cắm adapter bàn tay '
                           'hoặc đặt PORT cụ thể để tránh chọn nhầm thiết bị.')
    candidates = [p.device for p in ports if p.vid is not None or any(
        word in p.description.lower() for word in ('ch343', 'ch340', 'cp210', 'usb', 'ftdi'))]
    if len(candidates) == 1:
        print('PASS — Tự chọn cổng bàn tay:', candidates[0])
        return candidates[0]
    raise RuntimeError('Không xác định duy nhất cổng bàn tay. Cắm nguồn/USB và kiểm tra driver; '
                       f'các cổng hiện có: {[(p.device, p.description) for p in ports]}. '
                       'Đặt PORT hoặc config.port bằng tên cổng cụ thể; '
                       'game camera có thể dùng robot_enabled=False để không cần serial.')


def _download(url, destination):
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + '.part')
    try:
        with urllib.request.urlopen(url, timeout=60) as response, temporary.open('wb') as stream:
            while chunk := response.read(1024*1024):
                stream.write(chunk)
        return temporary
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def ensure_rps_model(root, relative_path='models/rps.h5'):
    root = Path(root)
    path = root / relative_path
    if relative_path != 'models/rps.h5':
        if not path.is_file():
            raise FileNotFoundError(f'Model tùy chỉnh chưa có: {path}')
        return path
    info = json.loads((root / 'models/rps.metadata.json').read_text(encoding='utf-8'))
    def valid(candidate):
        return candidate.is_file() and hashlib.sha256(candidate.read_bytes()).hexdigest() == info['sha256']
    if not valid(path):
        print('Tải checkpoint RPS đã train từ repo (~27 MB)...', flush=True)
        temporary = _download(info['download_url'], path)
        try:
            if not valid(temporary):
                raise RuntimeError('Checksum RPS không khớp. git pull bản mới rồi chạy lại cell tải model.')
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)
    print('PASS — RPS local, SHA-256 khớp:', path)
    return path


def ensure_training_dataset(root):
    """Tải train/test chính thức một lần; không cần tài khoản Kaggle."""
    root = Path(root).resolve()
    dataset = root / 'input/Rock-Paper-Scissors'
    for split, archive_name, expected in (('train', 'rps.zip', 2520), ('test', 'rps-test-set.zip', 372)):
        destination = dataset / split
        if all((destination / label).is_dir() for label in ('rock','paper','scissors')) and len(list(destination.rglob('*.png'))) == expected:
            continue
        archive = root / 'input' / archive_name
        if not archive.is_file() or not zipfile.is_zipfile(archive):
            print(f'Tải dataset {split}: {archive_name}...', flush=True)
            temporary = _download('https://storage.googleapis.com/download.tensorflow.org/data/' + archive_name, archive)
            if not zipfile.is_zipfile(temporary):
                temporary.unlink(missing_ok=True)
                raise RuntimeError('Dataset tải về không phải ZIP hợp lệ.')
            temporary.replace(archive)
        destination.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(archive) as bundle:
            for member in bundle.infolist():
                parts = Path(member.filename).parts
                if len(parts) < 3 or parts[1] not in ('rock','paper','scissors') or not member.filename.endswith('.png'):
                    continue
                target = destination.joinpath(*parts[1:]).resolve()
                if not target.is_relative_to(destination.resolve()):
                    raise RuntimeError('Đường dẫn dataset không hợp lệ.')
                target.parent.mkdir(parents=True, exist_ok=True)
                with bundle.open(member) as source, target.open('wb') as output:
                    while chunk := source.read(1024*1024):
                        output.write(chunk)
        if len(list(destination.rglob('*.png'))) != expected:
            raise RuntimeError(f'Dataset {split} thiếu ảnh; kiểm tra Internet rồi chạy lại cell.')
    print('PASS — Dataset train/test local:', dataset)
    return dataset
