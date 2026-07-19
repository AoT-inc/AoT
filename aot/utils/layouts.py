# coding=utf-8
#
#  이 소프트웨어는 오픈소스 Mycodo 프로젝트(© Kyle T. Gabriel)를 기반으로,
#  AoT 프로젝트 목적에 맞게 수정된 파생 버전입니다.
#  This software is a derivative work of the open-source Mycodo project (© Kyle T. Gabriel),
#  modified by AoT for use in its own smart agriculture systems.
#
#  Copyright (C) 2025 AoT (aot.inc.kr@gmail.com)
#  Copyright (C) 2015–2020 Kyle T. Gabriel <mycodo@kylegabriel.com>
#
#  본 파일은 GNU General Public License, 버전 3 또는 그 이후 버전에 따라 배포됩니다.
#  This file is licensed under the GNU General Public License, version 3 or (at your option) any later version.
#
#  본 소프트웨어는 유용하게 사용될 수 있으리라는 기대 하에 배포되며,
#  상품성이나 특정 목적에의 적합성에 대한 어떠한 보증도 제공하지 않습니다.
#  This software is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.
#
#  이 라이선스 사본은 함께 제공되어야 하며,
#  제공되지 않은 경우, 아래에서 확인할 수 있습니다:
#  You should have received a copy of the GNU General Public License
#  along with this software. If not, see <https://www.gnu.org/licenses/>.
#
#  --------------------------------------------------------------
#  원본 프로젝트 정보 / Original Project Info:
#
#  Project: Mycodo (https://github.com/kizniche/Mycodo)
#  Author:  Kyle T. Gabriel (https://kylegabriel.com)
#  License: GNU GPLv3
#
#  수정자 / Modified by:
#    - Organization: AoT (Agriculture of Things)
#    - Contact: aot.inc.kr@gmail.com
#
#  리포맷 날짜 / Reformatted: 2025-04-21
#  --------------------------------------------------------------

import logging
import os
import shutil

from aot.config import PATH_TEMPLATE_LAYOUT
from aot.config import PATH_TEMPLATE_LAYOUT_DEFAULT

logger = logging.getLogger("aot.utils.layouts")


def update_layout(custom_layout):
    try:
        # Reject obviously invalid content (None string, too short to be a real template)
        if custom_layout and isinstance(custom_layout, str):
            stripped = custom_layout.strip()
            if stripped.lower() == 'none' or len(stripped) < 10:
                custom_layout = None
        if custom_layout:
            # Use custom layout
            try:
                with open(PATH_TEMPLATE_LAYOUT, "w") as template:
                    template.write(custom_layout)
            except PermissionError:
                logger.warning("Could not write custom layout on SMB (Read-Only). Skipping.")
        else:
            # Use default layout
            if (os.path.exists(PATH_TEMPLATE_LAYOUT) and
                    not os.path.samefile(PATH_TEMPLATE_LAYOUT, PATH_TEMPLATE_LAYOUT_DEFAULT)):
                # Delete current layout if it's different from the default
                try:
                    os.remove(PATH_TEMPLATE_LAYOUT)
                except PermissionError:
                    logger.warning("Could not remove layout on SMB (Read-Only). Skipping.")
            
            try:
                shutil.copy(PATH_TEMPLATE_LAYOUT_DEFAULT, PATH_TEMPLATE_LAYOUT)
            except PermissionError:
                logger.warning("Could not copy default layout on SMB (Read-Only). Skipping.")
    except:
        logger.exception("Generating layout")
