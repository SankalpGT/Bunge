import boto3
import json
from config import BUCKET_NAME, REGION

s3 = boto3.client("s3", region_name=REGION)

def upload_to_s3(content, key):
    s3.put_object(Body=json.dumps(content, indent=2), Bucket=BUCKET_NAME, Key=key)

def list_files_in_folder(prefix):
    response = s3.list_objects_v2(Bucket=BUCKET_NAME, Prefix=prefix)
    return [f["Key"] for f in response.get("Contents", []) if f["Key"].endswith(".json")]

def download_json_from_s3(key):
    obj = s3.get_object(Bucket=BUCKET_NAME, Key=key)
    return json.loads(obj['Body'].read().decode())