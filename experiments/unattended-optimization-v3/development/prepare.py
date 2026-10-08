"""Owner-only native preparation; this module never calls a model or benchmark."""
from __future__ import annotations
import dataclasses
import importlib.util
import json
import os
from pathlib import Path
import time
from .core import IntegrityError, file_hash, write_new
from .native_backend import NativeBackend, NativeConfig, ProcessLimits, run_process

# Tool installations have explicit deployed paths, not guessed repository ancestry.
DEFAULT_TOOL_ROOT = Path('/workspace/scratch/eeae3ae186b3/profiling-tools/root')
DEFAULT_COMPILER = '/usr/bin/g++-14'


def pin_config(config):
    """Owner rebuilds pins after selecting its fixture/suite config, before use."""
    config = dataclasses.replace(config, pinned_files={})
    required = NativeBackend(config).required_pins()
    return dataclasses.replace(config, pinned_files={p: file_hash(p) for p in sorted(required)})


def prepare_native(root, destination, *, definitions=None, tool_root=DEFAULT_TOOL_ROOT, compiler=DEFAULT_COMPILER):
    """Create a fresh, retained native setup directory and return NativeBackend.

    Generates canonical public fixtures by default, compiles driver, records all
    paths/hashes/settings. Never profiles, benchmarks, performs inference or
    claims setup is a study freeze. Existing destination is always refused.
    The host is responsible for serializing preparation with all other native
    load and supplying output paths outside participant writable roots.
    """
    root, destination, tool_root = Path(root).resolve(), Path(destination).resolve(), Path(tool_root).resolve()
    destination.mkdir(parents=True, exist_ok=False)
    definitions = Path(definitions or root / 'development/native/definitions.draft.json').resolve()
    write_new(destination / 'preparation-start.json', {'status': 'setup_only_not_freeze', 'started_unix': time.time(), 'definitions': str(definitions), 'definitions_sha256': file_hash(definitions), 'native_benchmark_run': False, 'model_inference_run': False})
    spec = importlib.util.spec_from_file_location('v2_public_fixture_generation', root / 'development/native/generate_public.py')
    generator = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(generator)
    generator.generate(definitions, destination / 'public-fixtures')
    cpus = tuple(sorted(os.sched_getaffinity(0))[:2])
    if len(cpus) != 2:
        raise IntegrityError('study requires two allowed logical CPUs')
    ordinary = ProcessLimits(cpus, 1024**3, 512*1024, 64*1024**2, 30, 30)
    diagnostic = ProcessLimits(cpus, 4*1024**3, 2*1024**2, 64*1024**2, 180, 200)
    compile_limits = dataclasses.replace(ordinary, cpu_seconds=120, wall_seconds=120)
    driver = destination / 'driver'
    command = [compiler, '-std=c++20', '-O2', '-g', '-I', str(root / 'task/contract'), '-I', str(tool_root / 'usr/include'), str(root / 'development/native/driver.cpp'), '-ldl', '-o', str(driver)]
    result = run_process(command, destination / 'driver-build', destination, compile_limits, {'check_active': lambda: None})
    if result['status'] != 'pass':
        raise IntegrityError('native driver setup build failed; retained command record')
    config = NativeConfig(str(root / 'task/contract'), compiler, str(driver), str(destination / 'public-fixtures'),
                          str(tool_root / 'usr/bin/valgrind'), str(tool_root / 'usr/bin/callgrind_annotate'),
                          str(tool_root / 'usr/libexec/valgrind'), str(tool_root), ordinary, diagnostic, {})
    config = pin_config(config)
    write_new(destination / 'native-config.json', dataclasses.asdict(config))
    backend = NativeBackend(config)
    write_new(destination / 'preparation-result.json', {**backend.verify(), 'status': 'prepared_not_frozen', 'native_benchmark_run': False, 'model_inference_run': False, 'canonical_scale': definitions.name == 'definitions.draft.json'})
    return backend
