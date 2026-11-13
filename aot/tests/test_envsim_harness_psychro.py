# coding=utf-8
"""폐루프 하네스는 시설 물성(psychro)을 하네스 판 복사본에서 읽어야 한다.

`run.sh` 는 sim/*.py 와 psychro 를 결과 폴더의 `.harness/envsim/` 에 복사하고,
컨테이너의 PYTHONPATH 에는 시험 대상 코드(-c)를 올린다. sim 이 `aot.utils.psychro`
를 먼저 찾으면 시험 대상 판의 물성이 끼어들어 A/B 의 시설이 달라진다(오류 없이).
"""
import os
import shutil
import subprocess
import sys

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
SIM = os.path.join(REPO, 'aot', 'functions', 'utils', 'env_control', 'sim')


def test_harness_stage_uses_copied_psychro_even_with_repo_on_path(tmp_path):
    stage = tmp_path / 'envsim'
    stage.mkdir()
    for name in os.listdir(SIM):
        if name.endswith('.py'):
            shutil.copy(os.path.join(SIM, name), stage / name)
    shutil.copy(os.path.join(REPO, 'aot', 'utils', 'psychro.py'), stage / '_psychro.py')
    code = ('import envsim.plant as p, envsim.metrics as m;'
            'print(p.ps.__file__); print(m._psychro().__file__)')
    env = dict(os.environ, PYTHONPATH=os.pathsep.join([str(tmp_path), REPO]))
    out = subprocess.run([sys.executable, '-c', code], env=env, cwd=str(tmp_path),
                         capture_output=True, text=True, check=True).stdout.split()
    expected = str(stage / '_psychro.py')
    assert out == [expected, expected]
