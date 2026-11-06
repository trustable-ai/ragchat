import os
import boto3
import requests
import base64

def ingest(args):
    """
    Ingest a PDF, upload to S3, extract text using Tika, and store result back to S3.

    Args:
        args: dict with 'filename' (S3 key), 'fileContent' (base64) and S3 credentials

    Returns:
        dict with 'output' containing the extracted text and signed URL
    """
    # Get S3 configuration
    host = args.get("S3_HOST", os.getenv("S3_HOST"))
    port = args.get("S3_PORT", os.getenv("S3_PORT"))
    s3_url = f"http://{host}:{port}"
    access_key = args.get("S3_ACCESS_KEY", os.getenv("S3_ACCESS_KEY"))
    secret_key = args.get("S3_SECRET_KEY", os.getenv("S3_SECRET_KEY"))
    bucket = args.get("S3_BUCKET_DATA", os.getenv("S3_BUCKET_DATA"))

    # Get filename and file content from input.
    # `parts` (list of S3 keys) is used when the browser chunked the file
    # across multiple <1 MB uploads (rag/upload). `fileContent` is the legacy
    # small-file inline base64 path. A bare `filename` reads a single S3 key.
    filename = args.get("filename")
    file_content_b64 = args.get("fileContent")
    parts = args.get("parts")

    if not filename and not parts:
        return {"error": "filename parameter is required"}

    # Initialize S3 client
    s3_client = boto3.client(
        's3',
        region_name='us-east-1',
        endpoint_url=s3_url,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key
    )

    try:
        if file_content_b64:
            # Legacy small-file path: PDF sent inline as base64 in the request body.
            pdf_content = base64.b64decode(file_content_b64)
            # Upload PDF to S3 so it is stored alongside the extracted text
            s3_client.put_object(
                Bucket=bucket,
                Key=filename,
                Body=pdf_content,
                ContentType='application/pdf'
            )
        elif isinstance(parts, list) and parts:
            # Chunked upload path: the browser uploaded each chunk as its own
            # S3 object via rag/upload. Read and concatenate them in order.
            pieces = []
            for key in parts:
                obj = s3_client.get_object(Bucket=bucket, Key=key)
                pieces.append(obj['Body'].read())
            pdf_content = b"".join(pieces)
            if not pdf_content:
                return {"error": "uploaded file is empty"}
            # Persist the reassembled PDF so it lives alongside the extracted text.
            if filename:
                s3_client.put_object(
                    Bucket=bucket,
                    Key=filename,
                    Body=pdf_content,
                    ContentType='application/pdf'
                )
        else:
            # Single-key read: the browser uploaded the whole PDF to S3 already.
            obj = s3_client.get_object(Bucket=bucket, Key=filename)
            pdf_content = obj['Body'].read()
            if not pdf_content:
                return {"error": "uploaded file is empty"}

        # Call Tika service in Kubernetes (tika in current namespace)
        tika_url = "http://tika:9998/tika"
        tika_response = requests.put(
            tika_url,
            data=pdf_content,
            headers={'Accept': 'text/plain'},
            timeout=60
        )

        if tika_response.status_code != 200:
            return {"error": f"Tika extraction failed: {tika_response.status_code}"}

        extracted_text = tika_response.text

        # Store extracted text back to S3
        base_name = (filename or (parts[0] if parts else "output"))
        # Strip a trailing .partN chunk suffix so the output name is clean.
        import re
        base_name = re.sub(r'\.part\d+$', '', base_name)
        output_filename = base_name.replace('.pdf', '_extracted.txt')
        if output_filename == base_name:
            output_filename = base_name + '_extracted.txt'
        s3_client.put_object(
            Bucket=bucket,
            Key=output_filename,
            Body=extracted_text.encode('utf-8'),
            ContentType='text/plain'
        )

        # Generate signed URL for the extracted text (expires in 1 hour)
        signed_url = s3_client.generate_presigned_url(
            'get_object',
            Params={'Bucket': bucket, 'Key': output_filename},
            ExpiresIn=3600
        )

        return {
            "output": extracted_text,
            "filename": output_filename,
            "signed_url": signed_url
        }

    except Exception as e:
        return {"error": str(e)}
