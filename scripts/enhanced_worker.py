"""Isolated MinerU worker. Run only with the project MinerU interpreter.

The worker blocks all socket connections during import and inference. It writes
content only to the caller-provided project-local output directory and emits no
document text to stdout or stderr.
"""
import argparse
from contextlib import redirect_stderr, redirect_stdout
import io
import json
import os
from pathlib import Path
import socket
import sys
import time


def atomic_json(path, value):
    temporary = path.with_name(path.name + '.tmp')
    data = (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + '\n').encode('utf-8')
    with temporary.open('xb') as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


def block_network():
    def denied(*_args, **_kwargs):
        raise RuntimeError('NETWORK_DISABLED')
    socket.create_connection = denied
    socket.socket.connect = denied
    socket.socket.connect_ex = denied


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--input', required=True)
    parser.add_argument('--page', required=True, type=int)
    parser.add_argument('--output-dir', required=True)
    parser.add_argument('--tier', choices=('basic', 'standard', 'advanced'), default='standard')
    args = parser.parse_args(argv)
    output = Path(args.output_dir).absolute()
    report_path = output / 'worker-report.json'
    # The controller may render the immutable input-page preview before
    # launching MinerU.  No other pre-existing files are accepted.
    existing = {item.name for item in output.iterdir()} if output.is_dir() else set()
    if (args.page < 1 or not output.is_dir()
            or not existing.issubset({'page-preview.png'})
            or any(item.is_dir() for item in output.iterdir())):
        return 2
    if os.environ.get('MINERU_MODEL_SOURCE') != 'local':
        atomic_json(report_path, {'ok': False, 'error': 'LOCAL_MODEL_SOURCE_REQUIRED'})
        return 2
    for name in ('HF_HUB_OFFLINE', 'TRANSFORMERS_OFFLINE'):
        if os.environ.get(name) != '1':
            atomic_json(report_path, {'ok': False, 'error': 'OFFLINE_MODE_REQUIRED'})
            return 2
    block_network()
    sink = io.StringIO()
    started = time.perf_counter()
    try:
        with redirect_stdout(sink), redirect_stderr(sink):
            import importlib.metadata
            from mineru.parser import MinerUParser
            version = importlib.metadata.version('mineru')
            init_started = time.perf_counter()
            engine = MinerUParser(tier=args.tier, parse_mode='auto', image_analysis=True)
            init_seconds = time.perf_counter() - init_started
            parse_started = time.perf_counter()
            result = engine.parse(Path(args.input), page_range=str(args.page))
            parse_seconds = time.perf_counter() - parse_started
            markdown = result.markdown()
            structured = result.to_json()
        (output / 'mineru.md').write_text(markdown, encoding='utf-8', newline='\n')
        (output / 'mineru-result.json').write_text(structured, encoding='utf-8', newline='\n')
        atomic_json(report_path, {
            'ok': True,
            'parser_id': 'enhanced_mineru_standard',
            'parser_version': version,
            'tier': args.tier,
            'small_backend': 'onnx',
            'vlm_engine': 'llama-cpp',
            'page_number': args.page,
            'constructor_seconds': round(init_seconds, 3),
            'cold_model_load_and_page_seconds': round(parse_seconds, 3),
            'total_seconds': round(time.perf_counter() - started, 3),
            'network_policy': 'socket_connections_blocked',
        })
        return 0
    except Exception:
        atomic_json(report_path, {
            'ok': False, 'error': 'LOCAL_INFERENCE_FAILED',
            'page_number': args.page,
            'elapsed_seconds': round(time.perf_counter() - started, 3),
            'network_policy': 'socket_connections_blocked',
        })
        return 1


if __name__ == '__main__':
    sys.exit(main())
