"""Isolated local PaddleOCR-VL worker. It never accepts a PDF or a URL."""
import argparse
from contextlib import redirect_stderr, redirect_stdout
import io
import json
import os
from pathlib import Path
import socket
import stat
import sys
import time

PROJECT_ROOT = Path(__file__).absolute().parent.parent


def safe_local_path(path, root, required_prefix):
    path = Path(path).absolute()
    root = Path(root).absolute()
    try:
        relative = path.relative_to(root)
    except ValueError:
        return False
    if not relative.parts or relative.parts[0] != required_prefix:
        return False
    current = root
    for part in relative.parts:
        current = current / part
        if current.exists():
            info = current.lstat()
            attrs = getattr(info, 'st_file_attributes', 0)
            if stat.S_ISLNK(info.st_mode) or attrs & getattr(
                    stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0):
                return False
    return True


def atomic_json(path, value):
    temporary = path.with_name(path.name + '.tmp')
    data = (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + '\n').encode('utf-8')
    with temporary.open('xb') as stream:
        stream.write(data); stream.flush(); os.fsync(stream.fileno())
    temporary.replace(path)


def block_network():
    def denied(*_args, **_kwargs):
        raise RuntimeError('NETWORK_DISABLED')
    socket.create_connection = denied
    socket.socket.connect = denied
    socket.socket.connect_ex = denied


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--input-image', required=True)
    parser.add_argument('--output-dir', required=True)
    parser.add_argument('--layout-model', required=True)
    parser.add_argument('--vl-model', required=True)
    parser.add_argument('--pipeline-version', choices=('v1', 'v1.5', 'v1.6'), required=True)
    parser.add_argument('--device', default='gpu:0')
    args = parser.parse_args(argv)
    image = Path(args.input_image).absolute()
    output = Path(args.output_dir).absolute()
    report_path = output / 'worker-report.json'
    layout = Path(args.layout_model).absolute()
    vl_model = Path(args.vl_model).absolute()
    if (not safe_local_path(output, PROJECT_ROOT, 'vault')
            or not safe_local_path(image, PROJECT_ROOT, 'vault')
            or image.parent != output or not output.name.startswith('.tmp-page-')
            or not safe_local_path(layout, PROJECT_ROOT, 'models')
            or not safe_local_path(vl_model, PROJECT_ROOT, 'models')
            or not image.is_file() or image.suffix.lower() != '.png' or not output.is_dir()
            or not layout.is_dir() or not vl_model.is_dir()):
        return 2
    block_network()
    sink = io.StringIO(); started = time.perf_counter()
    try:
        with redirect_stdout(sink), redirect_stderr(sink):
            import importlib.metadata
            from paddleocr import PaddleOCRVL
            version = importlib.metadata.version('paddleocr')
            init_started = time.perf_counter()
            pipeline = PaddleOCRVL(
                pipeline_version=args.pipeline_version,
                layout_detection_model_dir=str(layout),
                vl_rec_model_dir=str(vl_model),
                vl_rec_backend='native', device=args.device,
                use_doc_orientation_classify=False, use_doc_unwarping=False,
                use_layout_detection=True, use_chart_recognition=False,
                use_seal_recognition=False, use_ocr_for_image_block=False,
                use_queues=False)
            init_seconds = time.perf_counter() - init_started
            infer_started = time.perf_counter()
            results = pipeline.predict(str(image))
            inference_seconds = time.perf_counter() - infer_started
            if len(results) != 1:
                raise RuntimeError('UNEXPECTED_RESULT_COUNT')
            result = results[0]
            result.save_to_markdown(str(output / 'paddleocr.md'))
            result.save_to_json(str(output / 'paddleocr-result.json'))
        atomic_json(report_path, {
            'ok': True, 'parser_id': 'paddleocr_vl_local',
            'parser_version': version, 'pipeline_version': args.pipeline_version,
            'device': args.device, 'page_count': 1,
            'constructor_seconds': round(init_seconds, 3),
            'inference_seconds': round(inference_seconds, 3),
            'total_seconds': round(time.perf_counter() - started, 3),
            'network_policy': 'socket_connections_blocked',
            'suppressed_diagnostic_bytes': len(sink.getvalue().encode('utf-8')),
        })
        return 0
    except Exception:
        atomic_json(report_path, {
            'ok': False, 'error': 'LOCAL_INFERENCE_FAILED',
            'elapsed_seconds': round(time.perf_counter() - started, 3),
            'network_policy': 'socket_connections_blocked',
            'suppressed_diagnostic_bytes': len(sink.getvalue().encode('utf-8')),
        })
        return 1


if __name__ == '__main__':
    sys.exit(main())
