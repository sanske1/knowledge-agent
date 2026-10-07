"""
loadfile: 文件识别与读取模块

职责：纯 IO 与解析，不做任何 AI 生成、不做语义加工。
输出：标准化 FileRaw 对象列表。
"""
import os
import sys
import hashlib
import time
from typing import Union, List

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

from .config import (
    TEXT_EXTENSIONS, OFFICE_EXTENSIONS, ENCODING_TRIES,
    MAX_FILE_SIZE, WARN_FILE_SIZE,
)
from .models import FileRaw, Paragraph


# ==================== 编码检测 ====================
def detect_encoding(file_path: str) -> str:
    """
    编码自动识别：依次尝试 UTF-8/GBK/GB2312/UTF-16/Latin-1。
    无 chardet 依赖时使用逐编码试探策略。
    """
    for enc in ENCODING_TRIES:
        try:
            with open(file_path, "r", encoding=enc) as f:
                f.read()
            return enc
        except (UnicodeDecodeError, UnicodeError):
            continue
        except Exception:
            break
    return "latin-1"  # 兜底


# ==================== 纯文本读取 ====================
def read_text_file(file_path: str) -> tuple:
    """
    读取纯文本类文件，返回 (content, paragraphs)。
    保留段落、换行、缩进结构。
    """
    encoding = detect_encoding(file_path)
    with open(file_path, "r", encoding=encoding, errors="replace") as f:
        content = f.read()

    # 按双换行分段，保留单换行作为段内换行
    paragraphs = []
    pos = 0
    for para_text in content.split("\n\n"):
        if para_text.strip():
            start = content.find(para_text, pos)
            end = start + len(para_text)
            paragraphs.append(Paragraph(
                text=para_text,
                start_pos=start,
                end_pos=end,
            ))
            pos = end
    return content, paragraphs


# ==================== 办公文档读取（按需导入，缺失则降级）====================
def read_pdf(file_path: str) -> tuple:
    """读取 PDF：优先 pypdf，备选 pdfplumber。"""
    # 优先 pypdf（轻量，已内置依赖）
    try:
        from pypdf import PdfReader
        reader = PdfReader(file_path)
        content_parts = []
        paragraphs = []
        for page_num, page in enumerate(reader.pages, 1):
            page_text = page.extract_text() or ""
            content_parts.append(page_text)
            offset = sum(len(p) for p in content_parts[:page_num-1])
            for para_text in page_text.split("\n\n"):
                if para_text.strip():
                    start = offset + page_text.find(para_text)
                    paragraphs.append(Paragraph(
                        text=para_text, start_pos=start,
                        end_pos=start + len(para_text), page=page_num,
                    ))
        return "\n\n".join(content_parts), paragraphs
    except ImportError:
        pass
    # 备选 pdfplumber
    try:
        import pdfplumber
        content_parts = []
        paragraphs = []
        with pdfplumber.open(file_path) as pdf:
            for page_num, page in enumerate(pdf.pages, 1):
                page_text = page.extract_text() or ""
                content_parts.append(page_text)
                offset = sum(len(p) for p in content_parts[:page_num-1])
                for para_text in page_text.split("\n\n"):
                    if para_text.strip():
                        start = offset + page_text.find(para_text)
                        paragraphs.append(Paragraph(
                            text=para_text, start_pos=start,
                            end_pos=start + len(para_text), page=page_num,
                        ))
        return "\n\n".join(content_parts), paragraphs
    except ImportError:
        raise RuntimeError("未安装 pypdf 或 pdfplumber，无法解析 PDF。请执行: pip install pypdf")


def read_doc(file_path: str) -> tuple:
    """读取旧版 .doc：优先 win32com 转 .docx，备选 olefile 提取文本。"""
    import tempfile
    # 方案1：通过 Word COM 转存为 .docx 再解析（Windows + 已装 Word）
    word = None
    doc = None
    tmp_path = None
    try:
        import win32com.client
        import pythoncom
        pythoncom.CoInitialize()
        word = win32com.client.DispatchEx("Word.Application")
        word.Visible = False
        word.DisplayAlerts = 0  # 禁用弹窗
        tmp_path = tempfile.mktemp(suffix=".docx")
        doc = word.Documents.Open(os.path.abspath(file_path), ReadOnly=True)
        doc.SaveAs(tmp_path, FileFormat=16)  # 16 = wdFormatXMLDocument (.docx)
        doc.Close(False)
        doc = None
    except Exception as e:
        print(f"[read_doc] win32com 转换失败: {e}")
    finally:
        # 无论成功失败都关闭 Word
        if doc is not None:
            try:
                doc.Close(False)
            except Exception:
                pass
        if word is not None:
            try:
                word.Quit()
            except Exception:
                pass
        try:
            pythoncom.CoUninitialize()
        except Exception:
            pass

    # 转换成功则读取 docx（Quit 失败不影响已保存的文件）
    if tmp_path and os.path.exists(tmp_path):
        try:
            content, paragraphs = read_docx(tmp_path)
            try:
                os.remove(tmp_path)
            except OSError:
                pass
            if not _is_garbage_text(content):
                return content, paragraphs
            print("[read_doc] win32com 提取文本质量过低，尝试 olefile 方案")
        except Exception as e:
            print(f"[read_doc] 读取转换后的 docx 失败: {e}，尝试 olefile 方案")
    # 方案2：olefile 提取 WordDocument 流中的文本（粗糙，需质量检查）
    try:
        import olefile
        ole = olefile.OleFileIO(file_path)
        text = ""
        if ole.exists("WordDocument"):
            stream = ole.openstream("WordDocument").read()
            # 简单提取可打印 ASCII/中文区间
            i = 0
            while i < len(stream):
                b = stream[i]
                if 0x20 <= b <= 0x7E or b == 0x09 or b == 0x0A or b == 0x0D:
                    text += chr(b)
                elif b >= 0x80 and i + 1 < len(stream):
                    try:
                        ch = stream[i:i+2].decode("gbk", errors="ignore")
                        if ch and ch.isprintable():
                            text += ch
                            i += 1
                    except Exception:
                        pass
                i += 1
        ole.close()
        content = text.strip()
        # 质量检查：olefile 提取的文本如果乱码比例过高则丢弃
        if _is_garbage_text(content):
            raise RuntimeError("olefile 提取的文本乱码比例过高")
        paragraphs = []
        pos = 0
        for para_text in content.split("\n"):
            if para_text.strip():
                start = pos
                end = start + len(para_text)
                paragraphs.append(Paragraph(text=para_text, start_pos=start, end_pos=end))
                pos = end + 1
        return content, paragraphs
    except Exception as e:
        print(f"[read_doc] olefile 失败: {e}")
    raise RuntimeError("无法解析 .doc 文件：请安装 Word（win32com）或使用 .docx 格式")


def _is_garbage_text(text: str) -> bool:
    """
    判断文本是否为乱码。
    检测策略：
    1. 可打印字符比例 < 50% → 乱码
    2. 英文文本（ASCII 字母占比高）→ 正常
    3. 中文文本高频字密度 < 3% → 乱码
    """
    if not text or len(text) < 10:
        return True
    # 检测1：可打印字符比例
    printable = 0
    ascii_letters = 0
    for ch in text:
        o = ord(ch)
        if (0x20 <= o <= 0x7E) or (0x4E00 <= o <= 0x9FFF) or (0x3000 <= o <= 0x303F) or (0xFF00 <= o <= 0xFFEF):
            printable += 1
        if (0x41 <= o <= 0x5A) or (0x61 <= o <= 0x7A):
            ascii_letters += 1
    if printable / len(text) < 0.5:
        return True
    # 英文文本：ASCII 字母占比 > 30% 视为正常
    if ascii_letters / len(text) > 0.3:
        return False
    # 中文文本：高频字密度检测
    common_chars = set("的一是在了不和有大这主中人为上们来到地为子和我以他时用们要就会可对生下能而那得于着自之年过发后作里用道行所然家种事成方多经么去法学如都同现当没动起你出小机也经力线本电高量长党实定水深求正开外几三合都还由物其点业标准但西四去因只从想实日军者意无力它与长把机十民第公此已工使情明性知全三又关点正业外将两高间由问很最重物，并关")
    common_count = sum(1 for ch in text if ch in common_chars)
    if len(text) >= 100 and common_count / len(text) < 0.03:
        return True
    return False


def read_docx(file_path: str) -> tuple:
    """读取 DOCX：提取正文+标题层级。需要 python-docx。"""
    try:
        import docx
        doc = docx.Document(file_path)
        content_parts = []
        paragraphs = []
        pos = 0
        for para in doc.paragraphs:
            text = para.text
            if not text.strip():
                continue
            # 标题层级识别
            heading_level = None
            style_name = (para.style.name or "").lower()
            if style_name.startswith("heading"):
                try:
                    heading_level = int(style_name.replace("heading", "").strip())
                except ValueError:
                    heading_level = 1
            start = pos
            end = start + len(text)
            content_parts.append(text)
            paragraphs.append(Paragraph(
                text=text, start_pos=start, end_pos=end,
                heading_level=heading_level,
            ))
            pos = end + 1
        return "\n".join(content_parts), paragraphs
    except ImportError:
        raise RuntimeError("未安装 python-docx，无法解析 DOCX。请执行: pip install python-docx")


def read_xlsx(file_path: str) -> tuple:
    """读取 XLSX：提取表格文本（保留行列结构）。需要 openpyxl。"""
    try:
        import openpyxl
        wb = openpyxl.load_workbook(file_path, read_only=True, data_only=True)
        content_parts = []
        paragraphs = []
        pos = 0
        for sheet in wb.sheetnames:
            ws = wb[sheet]
            content_parts.append(f"【工作表: {sheet}】")
            for row in ws.iter_rows(values_only=True):
                row_text = " | ".join(str(c) if c is not None else "" for c in row)
                if row_text.strip(" |"):
                    content_parts.append(row_text)
        full_text = "\n".join(content_parts)
        for para_text in full_text.split("\n"):
            if para_text.strip():
                start = full_text.find(para_text, pos)
                end = start + len(para_text)
                paragraphs.append(Paragraph(text=para_text, start_pos=start, end_pos=end))
                pos = end
        wb.close()
        return full_text, paragraphs
    except ImportError:
        raise RuntimeError("未安装 openpyxl，无法解析 XLSX。请执行: pip install openpyxl")


def read_xls(file_path: str) -> tuple:
    """读取旧版 XLS：优先 xlrd，备选 win32com 转 xlsx。"""
    # 方案1：xlrd 直接读取
    try:
        import xlrd
        wb = xlrd.open_workbook(file_path)
        content_parts = []
        for sheet in wb.sheets():
            content_parts.append(f"【工作表: {sheet.name}】")
            for row_idx in range(sheet.nrows):
                row = sheet.row_values(row_idx)
                row_text = " | ".join(str(c) if c else "" for c in row)
                if row_text.strip(" |"):
                    content_parts.append(row_text)
        full_text = "\n".join(content_parts)
        paragraphs = []
        pos = 0
        for para_text in full_text.split("\n"):
            if para_text.strip():
                start = full_text.find(para_text, pos)
                end = start + len(para_text)
                paragraphs.append(Paragraph(text=para_text, start_pos=start, end_pos=end))
                pos = end
        return full_text, paragraphs
    except ImportError:
        pass
    except Exception:
        pass
    # 方案2：win32com 转 xlsx
    try:
        import win32com.client
        import pythoncom
        import tempfile
        pythoncom.CoInitialize()
        excel = win32com.client.DispatchEx("Excel.Application")
        excel.Visible = False
        excel.DisplayAlerts = False
        tmp_path = tempfile.mktemp(suffix=".xlsx")
        wb = excel.Workbooks.Open(os.path.abspath(file_path))
        wb.SaveAs(tmp_path, FileFormat=51)  # 51 = xlOpenXMLWorkbook
        wb.Close()
        excel.Quit()
        pythoncom.CoUninitialize()
        content, paragraphs = read_xlsx(tmp_path)
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        return content, paragraphs
    except Exception:
        pass
    raise RuntimeError("无法解析 .xls 文件：请安装 xlrd 或 Excel（win32com）")


def read_pptx(file_path: str) -> tuple:
    """读取 PPTX：提取每页文本。需要 python-pptx。"""
    try:
        from pptx import Presentation
        prs = Presentation(file_path)
        content_parts = []
        paragraphs = []
        pos = 0
        for slide_num, slide in enumerate(prs.slides, 1):
            slide_texts = [f"【第{slide_num}页】"]
            for shape in slide.shapes:
                if hasattr(shape, "text") and shape.text.strip():
                    slide_texts.append(shape.text)
            slide_full = "\n".join(slide_texts)
            content_parts.append(slide_full)
            start = pos
            end = start + len(slide_full)
            paragraphs.append(Paragraph(text=slide_full, start_pos=start, end_pos=end, page=slide_num))
            pos = end + 1
        return "\n\n".join(content_parts), paragraphs
    except ImportError:
        raise RuntimeError("未安装 python-pptx，无法解析 PPTX。请执行: pip install python-pptx")


def read_ppt(file_path: str) -> tuple:
    """读取旧版 PPT：通过 win32com 转 pptx 再解析。"""
    try:
        import win32com.client
        import pythoncom
        import tempfile
        pythoncom.CoInitialize()
        ppt = win32com.client.DispatchEx("PowerPoint.Application")
        tmp_path = tempfile.mktemp(suffix=".pptx")
        pres = ppt.Presentations.Open(os.path.abspath(file_path), WithWindow=False)
        pres.SaveAs(tmp_path, 24)  # 24 = ppSaveAsOpenXMLPresentation
        pres.Close()
        ppt.Quit()
        pythoncom.CoUninitialize()
        content, paragraphs = read_pptx(tmp_path)
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        return content, paragraphs
    except Exception:
        pass
    raise RuntimeError("无法解析 .ppt 文件：请安装 PowerPoint（win32com）或使用 .pptx 格式")


# ==================== 文件合法性校验 ====================
def is_valid_file(file_path: str) -> tuple:
    """
    合法性过滤：空文件、隐藏文件、临时文件、权限不足、超大文件。
    返回 (is_valid, reason)
    """
    name = os.path.basename(file_path)
    # 隐藏文件
    if name.startswith("."):
        return False, "隐藏文件"
    # 临时文件
    if name.endswith(("~", ".tmp", ".temp", ".bak")):
        return False, "临时文件"
    # 存在性
    if not os.path.isfile(file_path):
        return False, "文件不存在"
    # 权限
    if not os.access(file_path, os.R_OK):
        return False, "权限不足"
    # 大小
    try:
        size = os.path.getsize(file_path)
    except OSError:
        return False, "无法获取文件大小"
    if size == 0:
        return False, "空文件"
    if size > MAX_FILE_SIZE:
        return False, f"文件过大({size // 1024 // 1024}MB)，超过阈值{MAX_FILE_SIZE // 1024 // 1024}MB"
    return True, ""


# ==================== 分发读取 ====================
def parse_file(file_path: str) -> FileRaw:
    """
    根据后缀分发到对应解析器，输出 FileRaw。
    未知格式或解析失败时 success=False。
    """
    abs_path = os.path.abspath(file_path)
    name = os.path.basename(abs_path)
    ext = os.path.splitext(name)[1].lower()

    # 基础元数据
    try:
        stat = os.stat(abs_path)
        size = stat.st_size
        mtime = stat.st_mtime
    except OSError as e:
        return FileRaw(
            file_id="", abs_path=abs_path, filename=name, ext=ext,
            size=0, mtime=0, success=False, error=f"无法读取文件信息: {e}",
        )

    file_id = hashlib.md5(f"{abs_path}|{mtime}".encode("utf-8")).hexdigest()

    # 合法性校验
    valid, reason = is_valid_file(abs_path)
    if not valid:
        return FileRaw(
            file_id=file_id, abs_path=abs_path, filename=name, ext=ext,
            size=size, mtime=mtime, success=False, error=reason,
        )

    if size > WARN_FILE_SIZE:
        print(f"[loadfile] 告警: {name} 较大({size // 1024 // 1024}MB)，处理可能较慢")

    # 分发解析
    try:
        if ext in TEXT_EXTENSIONS:
            content, paragraphs = read_text_file(abs_path)
        elif ext == ".pdf":
            content, paragraphs = read_pdf(abs_path)
        elif ext == ".docx":
            content, paragraphs = read_docx(abs_path)
        elif ext == ".doc":
            content, paragraphs = read_doc(abs_path)
        elif ext == ".xlsx":
            content, paragraphs = read_xlsx(abs_path)
        elif ext == ".xls":
            content, paragraphs = read_xls(abs_path)
        elif ext == ".pptx":
            content, paragraphs = read_pptx(abs_path)
        elif ext == ".ppt":
            content, paragraphs = read_ppt(abs_path)
        else:
            return FileRaw(
                file_id=file_id, abs_path=abs_path, filename=name, ext=ext,
                size=size, mtime=mtime, success=False, error=f"不支持的格式: {ext}",
            )

        return FileRaw(
            file_id=file_id, abs_path=abs_path, filename=name, ext=ext,
            size=size, mtime=mtime, content=content, paragraphs=paragraphs,
            success=True,
        )
    except Exception as e:
        return FileRaw(
            file_id=file_id, abs_path=abs_path, filename=name, ext=ext,
            size=size, mtime=mtime, success=False, error=str(e),
        )


# ==================== 路径安全校验 ====================
def is_path_safe(file_path: str, root_dir: str = None) -> bool:
    """路径安全：限制访问指定根目录，禁止路径回溯。"""
    abs_path = os.path.abspath(file_path)
    if root_dir:
        abs_root = os.path.abspath(root_dir)
        if not abs_path.startswith(abs_root + os.sep) and abs_path != abs_root:
            return False
    # 禁止 .. 回溯
    if ".." in abs_path.split(os.sep):
        return False
    return True


# ==================== 批量收集文件 ====================
def collect_files(inputs: Union[str, List[str]], recursive: bool = True) -> List[str]:
    """
    收集待处理文件路径列表。
    支持：单个文件、文件列表、文件夹（可选递归）。
    """
    if isinstance(inputs, str):
        inputs = [inputs]

    file_list = []
    for item in inputs:
        if os.path.isdir(item):
            if recursive:
                for root, _, files in os.walk(item):
                    for f in files:
                        file_list.append(os.path.join(root, f))
            else:
                for f in os.listdir(item):
                    fp = os.path.join(item, f)
                    if os.path.isfile(fp):
                        file_list.append(fp)
        elif os.path.isfile(item):
            file_list.append(item)
        else:
            print(f"[loadfile] 跳过无效路径: {item}")
    return file_list


# ==================== 主入口 ====================
def loadfile(inputs: Union[str, List[str]], recursive: bool = True) -> List[FileRaw]:
    """
    文件入库第一步：批量识别 → 格式解析 → 输出标准化 FileRaw 列表。

    Args:
        inputs: 单个文件路径 / 文件路径列表 / 文件夹路径
        recursive: 文件夹是否递归子目录

    Returns:
        List[FileRaw]: 标准化文件对象列表（含失败项）
    """
    file_paths = collect_files(inputs, recursive=recursive)
    print(f"[loadfile] 收集到 {len(file_paths)} 个文件，开始解析...")

    results = []
    success_count = 0
    fail_count = 0
    for fp in file_paths:
        raw = parse_file(fp)
        results.append(raw)
        if raw.success:
            success_count += 1
            print(f"  ✅ {raw.filename} ({raw.ext}, {raw.size}B)")
        else:
            fail_count += 1
            print(f"  ❌ {raw.filename}: {raw.error}")

    print(f"[loadfile] 完成: 成功 {success_count}，失败 {fail_count}")
    return results


if __name__ == "__main__":
    # 快速测试
    if len(sys.argv) > 1:
        raws = loadfile(sys.argv[1])
        for r in raws:
            if r.success:
                print(f"\n--- {r.filename} ---")
                print(f"大小: {r.size}B, 段落数: {len(r.paragraphs)}")
                print(f"内容前200字: {r.content[:200]}")
