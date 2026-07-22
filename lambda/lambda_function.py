import json
import boto3
import uuid
import re
from datetime import datetime, timezone
from decimal import Decimal

dynamodb = boto3.resource('dynamodb')
s3 = boto3.client('s3')
table = dynamodb.Table('infra-requests')


def validate_bucket_name(name):
    if not name:
        return "Bucket name is required."
    if len(name) < 3 or len(name) > 63:
        return "Bucket name must be between 3 and 63 characters."
    if not re.match(r'^[a-z0-9][a-z0-9.-]*[a-z0-9]$', name):
        return "Bucket name must use only lowercase letters, numbers, hyphens, or periods, and must start/end with a letter or number."
    if '..' in name:
        return "Bucket name cannot contain consecutive periods."
    return None  # valid


def lambda_handler(event, context):
    # Handle CORS preflight requests from the browser
    if event.get('requestContext', {}).get('http', {}).get('method') == 'OPTIONS':
        return respond(200, {})

    # Parse body - Function URL sends it as a JSON string, test events send it as a dict
    body = event
    if 'body' in event and isinstance(event['body'], str):
        body = json.loads(event['body'])

    action = body.get('action')

    # Handle "list" - just reads DynamoDB, no S3 calls
    if action == 'list':
        try:
            result = table.scan()
            items = result.get('Items', [])
            items.sort(key=lambda x: x.get('requested_at', ''), reverse=True)
            return respond(200, {"items": items}, decimal_safe=True)
        except Exception as e:
            return respond(500, {"error": str(e)})

    resource_type = body.get('resource_type')
    bucket_name = body.get('bucket_name')

    request_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()

    if not action or not resource_type or not bucket_name:
        return respond(400, {"error": "Missing required fields: action, resource_type, bucket_name"})

    if resource_type != 's3_bucket':
        return respond(400, {"error": f"Unsupported resource_type: {resource_type}"})

    # Validate bucket name upfront, before touching AWS
    if action in ('create', 'delete'):
        validation_error = validate_bucket_name(bucket_name)
        if validation_error:
            return respond(400, {"error": validation_error})

    # 1. Write initial 'pending' record
    table.put_item(Item={
        'request_id': request_id,
        'resource_type': resource_type,
        'action': action,
        'status': 'pending',
        'requested_at': now,
        'updated_at': now,
        'details': {'bucket_name': bucket_name}
    })

    # 2. Try to perform the action
    try:
        if action == 'create':
            region = boto3.session.Session().region_name
            if region == 'us-east-1':
                s3.create_bucket(Bucket=bucket_name)
            else:
                s3.create_bucket(
                    Bucket=bucket_name,
                    CreateBucketConfiguration={'LocationConstraint': region}
                )
        elif action == 'delete':
            s3.delete_bucket(Bucket=bucket_name)
        else:
            raise ValueError(f"Unsupported action: {action}")

        update_status(request_id, 'complete')
        return respond(200, {"request_id": request_id, "status": "complete"})

    except s3.exceptions.ClientError as e:
        error_code = e.response.get('Error', {}).get('Code', '')
        if error_code == 'BucketNotEmpty':
            friendly_error = "This bucket still has objects in it. Empty the bucket before deleting it."
        elif error_code == 'BucketAlreadyExists' or error_code == 'BucketAlreadyOwnedByYou':
            friendly_error = "A bucket with this name already exists. Bucket names must be globally unique."
        elif error_code == 'NoSuchBucket':
            friendly_error = "This bucket doesn't exist — it may have already been deleted."
        else:
            friendly_error = str(e)
        update_status(request_id, 'failed', error=friendly_error)
        return respond(500, {"request_id": request_id, "status": "failed", "error": friendly_error})

    except Exception as e:
        update_status(request_id, 'failed', error=str(e))
        return respond(500, {"request_id": request_id, "status": "failed", "error": str(e)})


def update_status(request_id, status, error=None):
    update_expr = "SET #s = :s, updated_at = :u"
    expr_values = {
        ':s': status,
        ':u': datetime.now(timezone.utc).isoformat()
    }
    expr_names = {'#s': 'status'}

    if error:
        update_expr += ", error_message = :e"
        expr_values[':e'] = error

    table.update_item(
        Key={'request_id': request_id},
        UpdateExpression=update_expr,
        ExpressionAttributeValues=expr_values,
        ExpressionAttributeNames=expr_names
    )


class DecimalEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, Decimal):
            return int(obj) if obj % 1 == 0 else float(obj)
        return super().default(obj)


def respond(status_code, body, decimal_safe=False):
    return {
        'statusCode': status_code,
        'headers': {
            'Content-Type': 'application/json',
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Headers': 'Content-Type',
            'Access-Control-Allow-Methods': 'OPTIONS,POST'
        },
        'body': json.dumps(body, cls=DecimalEncoder) if decimal_safe else json.dumps(body)
    }
