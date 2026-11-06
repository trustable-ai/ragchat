import re
import unicodedata

def clean(args):
    """
    Clean extracted text by removing:
    - Lines with a single number (page numbers)
    - Lines with "Figure <number>"
    - Table of contents lines ending in "...<number>"
    - Strange/invalid characters (non-printable, corrupted unicode)
    - Common OCR artifacts
    - Multiple consecutive empty lines (keep at least one line separating paragraphs)

    Args:
        args: dict with 'input' containing the text to clean

    Returns:
        dict with 'output' containing cleaned UTF-8 text
    """
    text = args.get("input", "")

    if not text:
        return {"output": ""}

    lines = text.split('\n')
    cleaned_lines = []

    for line in lines:
        # Skip lines that are only numbers (page numbers)
        if re.match(r'^\s*\d+\s*$', line):
            continue

        # Skip lines with "Figure <number>" (case insensitive)
        if re.search(r'\bFigure\s+\d+\b', line, re.IGNORECASE):
            continue

        # Skip table of contents lines ending in "...<number>"
        if re.search(r'\.{2,}\s*\d+\s*$', line):
            continue

        # If line is empty, keep it as is (for paragraph separation)
        if not line.strip():
            cleaned_lines.append("")
            continue

        # Remove strange characters and clean the line
        cleaned_line = clean_line(line)

        # Only keep non-empty cleaned lines
        if cleaned_line.strip():
            cleaned_lines.append(cleaned_line)

    # Remove multiple consecutive empty lines, keeping only one
    result_lines = []
    prev_empty = False

    for line in cleaned_lines:
        is_empty = not line.strip()

        if is_empty:
            if not prev_empty:
                result_lines.append(line)
            prev_empty = True
        else:
            result_lines.append(line)
            prev_empty = False

    return {"output": '\n'.join(result_lines)}


def clean_line(line):
    """
    Clean a single line by removing strange characters and normalizing text.
    """
    # Normalize unicode characters
    line = unicodedata.normalize('NFKC', line)

    # Remove common corrupted characters and OCR artifacts
    # Replace curly quotes with straight quotes
    line = line.replace(''', "'").replace(''', "'")
    line = line.replace('"', '"').replace('"', '"')

    # Remove zero-width characters
    line = line.replace('\u200b', '')  # zero-width space
    line = line.replace('\u200c', '')  # zero-width non-joiner
    line = line.replace('\u200d', '')  # zero-width joiner
    line = line.replace('\ufeff', '')  # zero-width no-break space

    # Remove control characters except newlines and tabs
    line = ''.join(char for char in line if unicodedata.category(char)[0] != 'C' or char in '\n\t')

    # Handle the specific case where "â" appears at start of line (corrupted bullet)
    # Replace standalone "â" or similar artifacts at line start with bullet point
    line = re.sub(r'^\s*\u00E2\s+', '- ', line)

    # Remove common corrupted character sequences and encoding artifacts
    # Using regex to match common UTF-8 misinterpretations and mojibake
    # This handles cases where bullet points or other symbols become mojibake
    line = re.sub(r'[\u00C2\u00E2][\u0080-\u009F]+', '', line)

    # Remove any remaining standalone â characters (not followed by valid chars)
    line = line.replace('\u00E2', '')
    # Remove replacement character
    line = line.replace('\ufffd', '')
    # Remove non-breaking space artifacts
    line = line.replace('\u00A0', ' ')

    # Remove multiple spaces
    line = re.sub(r'\s+', ' ', line)

    # Remove leading/trailing whitespace
    line = line.strip()

    return line
