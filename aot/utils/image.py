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

logger = logging.getLogger("aot.utils.image")


def generate_thermal_image_from_pixels(
        pixels, nx, ny, path_file, rotate_ccw=270, scale=25, temp_min=None, temp_max=None):
    """Generate and save image from list of pixels."""
    from colour import Color
    from PIL import Image
    from PIL import ImageDraw

    if len(pixels) != nx * ny:
        logger.error("{nx} * {ny} does not equal {px}".format(
            nx=nx, ny=ny, px=len(pixels)))
        return

    # output image buffer
    image = Image.new("RGB", (nx, ny), "white")
    draw = ImageDraw.Draw(image)

    # color map
    COLORDEPTH = 256
    colors = list(Color("indigo").range_to(Color("red"), COLORDEPTH))
    colors = [(int(c.red * 255), int(c.green * 255), int(c.blue * 255)) for c in colors]

    # some utility functions
    def constrain(val, min_val, max_val):
        return min(max_val, max(min_val, val))

    def map_it(x, in_min, in_max, out_min, out_max):
        return (x - in_min) * (out_max - out_min) / (in_max - in_min) + out_min

    # map sensor readings to color map
    MINTEMP = min(pixels) if temp_min is None else temp_min
    MAXTEMP = max(pixels) if temp_max is None else temp_max
    pixels = [map_it(p, MINTEMP, MAXTEMP, 0, COLORDEPTH - 1) for p in pixels]

    # create the image
    for ix in range(nx):
        for iy in range(ny):
            draw.point([(ix, iy % nx)], fill=colors[constrain(int(pixels[ix + nx * iy]), 0, COLORDEPTH - 1)])

    if rotate_ccw:
        image = image.rotate(rotate_ccw)

    # scale and save
    image.resize((nx * scale, ny * scale), Image.BICUBIC).save(path_file)
