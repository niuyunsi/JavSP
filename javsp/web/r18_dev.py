"""从R18.dev抓取数据"""

import logging
import re
import requests
from datetime import datetime

from javsp.web.base import Request
from javsp.web.exceptions import *
from javsp.datatype import MovieInfo
from javsp.config import Cfg, CrawlerID

logger = logging.getLogger(__name__)
# 初始化Request实例
request = Request()
request.headers.update(
    {
        "User-Agent": "PlexJav18",
        "accept": "*/*",
    }
)

# 使用配置中的 proxy_free 地址，如果没有配置则使用默认地址
try:
    base_url = str(Cfg().network.proxy_free[CrawlerID.r18_dev])
except:
    base_url = "https://r18.dev"


def get_movie_data(dvdid: str, search_first=True):
    """获取影片的详细数据"""
    # 首先尝试通过dvd_id搜索
    if search_first:
        try:
            search_url = f'{base_url}/videos/vod/movies/detail/-/dvd_id={dvdid.replace("-", "").lower()}/json'
            logger.debug(f"Searching movie: {search_url}")
            resp = request.get(search_url, delay_raise=True)
            if resp.status_code == 200:
                data = resp.json()
                if data and "content_id" in data:
                    content_id = data["content_id"]
                    return get_movie_data_by_content_id(content_id)
            else:
                logger.debug(f"Search returned status code: {resp.status_code}")
        except Exception as e:
            logger.debug(f"Search by dvd_id failed: {e}")

    # 如果搜索失败，尝试直接使用content_id
    return get_movie_data_by_content_id(dvdid.replace("-", "").lower())


def get_movie_data_by_content_id(content_id: str):
    """通过content_id获取影片详细数据"""
    try:
        api_url = f"{base_url}/videos/vod/movies/detail/-/combined={content_id}/json"
        logger.debug(f"Fetching movie data: {api_url}")
        resp = request.get(api_url, delay_raise=True)
        if resp.status_code == 200:
            return resp.json()
        else:
            logger.debug(f"API returned status code: {resp.status_code}")
            return None
    except Exception as e:
        logger.debug(f"Failed to fetch movie data: {e}")
        return None


def parse_data(movie: MovieInfo):
    """解析指定番号的影片数据"""
    try:
        data = get_movie_data(movie.dvdid)
        if not data:
            raise MovieNotFoundError(__name__, movie.dvdid)
    except requests.exceptions.ConnectionError:
        logger.warning(
            f"R18.dev connection failed for {movie.dvdid} - site may be blocked or down"
        )
        raise SiteBlocked(__name__, movie.dvdid)
    except Exception as e:
        logger.error(f"R18.dev parsing failed for {movie.dvdid}: {e}")
        raise MovieNotFoundError(__name__, movie.dvdid)

    # 基本信息
    movie.url = f'{base_url}/videos/vod/movies/detail/-/combined={data.get("content_id", movie.dvdid)}'
    movie.dvdid = data.get("dvd_id") or ""
    movie.cid = data.get("content_id") or ""
    movie.title = data.get("title_ja") or data.get("title_en") or ""

    # 发行信息
    movie.producer = data.get("maker_name_ja") or data.get("maker_name_en") or ""
    movie.publisher = data.get("maker_name_ja") or data.get("maker_name_en") or ""

    # 发布日期
    release_date = data.get("release_date")
    if release_date and release_date != "0000-00-00":
        try:
            movie.publish_date = datetime.strptime(release_date, "%Y-%m-%d").strftime(
                "%Y-%m-%d"
            )
        except ValueError:
            pass

    # 导演
    directors = data.get("directors", [])
    if directors:
        director_names = []
        for director in directors:
            name = director.get("name_kanji") or director.get("name_romaji") or ""
            if name:
                director_names.append(name)
        if director_names:
            movie.director = ", ".join(director_names)

    # 系列
    movie.serial = data.get("series_name_ja") or data.get("series_name_en") or ""

    # 分类/类型
    categories = data.get("categories", [])
    if categories:
        genres = []
        for category in categories:
            genre_name = category.get("name_ja") or category.get("name_en") or ""
            if genre_name and genre_name not in genres:
                genres.append(genre_name)
        movie.genre = genres if genres else None

    # 演员
    actresses = data.get("actresses", [])
    if actresses:
        actress_names = []
        actress_pics = {}
        for actress in actresses:
            name = actress.get("name_kanji") or actress.get("name_romaji") or ""
            if name:
                actress_names.append(name)
                # 演员头像
                image_url = actress.get("image_url")
                if image_url:
                    actress_pics[name] = (
                        f"https://pics.dmm.co.jp/mono/actjpgs/{image_url}"
                    )
        movie.actress = actress_names if actress_names else None
        movie.actress_pics = actress_pics if actress_pics else None

    # 封面图片
    movie.cover = data.get("jacket_thumb_url")
    movie.big_cover = data.get("jacket_full_url")

    # 预览图片
    gallery = data.get("gallery", [])
    if gallery:
        preview_pics = []
        for scene in gallery:
            image_url = scene.get("image_full")
            if image_url:
                preview_pics.append(image_url)
        movie.preview_pics = preview_pics if preview_pics else None

    # 额外的封面图片
    extra_covers = []
    front_cover = get_front_cover(data)
    if front_cover:
        extra_covers.append(front_cover)
    movie.extra_covers = extra_covers if extra_covers else None

def parse_clean_data(movie: MovieInfo):
    """解析指定番号的影片数据并进行清洗"""
    parse_data(movie)

    # 简单的数据清理
    if movie.title:
        # 移除标题中的番号
        if movie.dvdid and movie.dvdid.upper() in movie.title.upper():
            movie.title = (
                movie.title.replace(movie.dvdid.upper(), "")
                .replace(movie.dvdid.lower(), "")
                .strip()
            )
        # 移除多余的空格
        movie.title = re.sub(r"\s+", " ", movie.title).strip()


def get_front_cover(data: dict) -> str | None:
    if data["service_code"] in ["mono"]:
        return (
            "https://awsimgsrc.dmm.com/dig/mono/movie/"
            + data["content_id"]
            + "/"
            + data["content_id"]
            + "ps.jpg"
        )
    if data["service_code"] in ["digital"]:
        return (
            "https://awsimgsrc.dmm.com/dig/digital/video/"
            + data["content_id"]
            + "/"
            + data["content_id"]
            + "ps.jpg"
        )
    else:
        return None
