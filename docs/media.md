# 富媒体与素材

## 支持的文件类型

| `FileType` | 值 | 格式 | 软限制 | 硬限制 |
|---|---|---|---|---|
| `IMAGE` | 1 | png / jpg | 20 MB | 200 MB |
| `VIDEO` | 2 | mp4 | 30 MB | 200 MB |
| `VOICE` | 3 | silk（文档另列出 mp3/wav/ogg） | 20 MB | 200 MB |
| `FILE` | 4 | 任意 | 200 MB | 200 MB |

超过软限制时平台会降级为文件类型；超过硬限制报错。单聊与群聊的上传接口相互隔离，上传得到的 `file_info` 不能跨场景使用。

## 上传方式

### 1. URL 上传

文件已在公网可访问：

```python
from qqbot_toolkit.api.media import MediaTarget
from qqbot_toolkit.constants import FileType

target = MediaTarget.group("GROUP_OPENID")
result = await bot.media.upload_url(
    target,
    FileType.IMAGE,
    "https://example.com/image.png",
)
await bot.group.send("GROUP_OPENID", media=result.file_info)
```

平台会自行下载并转存。下载失败时改用本地文件或分片上传。

### 2. 二进制直传

不超过 5 MiB 时可以直接 Base64 上传：

```python
result = await bot.media.upload_bytes(
    MediaTarget.c2c("USER_OPENID"),
    FileType.IMAGE,
    "image.png",
    data,
)
```

`file_data` 是 Base64 字符串，库内部完成编码。

### 3. 分片上传（推荐）

本地文件或大文件：

```python
result = await bot.media.upload_file(
    MediaTarget.group("GROUP_OPENID"),
    "video.mp4",
    srv_send_msg=False,
)
await bot.group.send("GROUP_OPENID", media=result.file_info)
```

内部流程：

```text
upload_prepare
  ├─ 计算 MD5 / SHA1 / 前 10002432 字节 MD5
  ├─ 返回 upload_id、block_size、各分片 presigned_url、upload_config
  │
  ├─ 对每个分片：读取 block_size 字节
  │    ├─ HTTP PUT 到 presigned_url
  │    └─ upload_part_finish（携带分片 MD5）
  │
  └─ POST /files {upload_id}
       └─ 返回 file_info
```

- 分片并发度使用服务端 `upload_config.concurrency`；
- 分片大小以服务端返回的 `block_size` 为准；
- `upload_config.retry_delay` 用于分片 PUT 的失败重试；
- `upload_file` 根据扩展名推断 `file_type`，也可以显式传入；
- `force_chunked=True` 可强制走分片流程。

### 4. 上传并直接发送

`srv_send_msg=True` 时平台在上传完成后直接发送消息，响应包含消息 ID，但会占用主动消息频次：

```python
result = await bot.media.upload_file(
    MediaTarget.group("GROUP_OPENID"),
    "image.png",
    srv_send_msg=True,
)
print(result.id)
```

## Markdown 图片素材

Markdown 中的公网图片 URL 会被平台转存。若图片没有公网地址，可先上传素材，得到 `qqbot-media://` 引用：

```python
image = await bot.media.upload_image("chart.png")
markdown = f"![K线 #800px #400px]({image.url})"
await bot.group.send("GROUP_OPENID", markdown=markdown)
```

素材限制：

| 项目 | 限制 |
|---|---|
| 单张大小 | 10 MB |
| 格式 | png / jpeg / gif / webp |
| 文件名与 Content-Type | 扩展名必须匹配 |
| 单机器人数量 | 100 张 |
| 有效期 | 滑动过期：连续 90 天未被引用则失效 |
| 上传任务有效期 | 4 小时 |

管理接口：

```python
page = await bot.media.list_images()
for item in page.images:
    print(item.image_id, item.expires_at)

await bot.media.delete_image(image.image_id)
```

删除后引用链接立即失效，但已发送消息中的副本不受影响。

## 发送富媒体消息

```python
# 直接发送 file_info
await bot.c2c.send(user_openid, media="FILE_INFO", msg_id=event.id, msg_seq=1)

# 也可以传 MediaInfo
from qqbot_toolkit.models.outbound import MediaInfo
await bot.group.send(group_openid, media=MediaInfo(file_info="FILE_INFO"))
```

富媒体消息和文本、Markdown 一样可以携带 `keyboard`、`message_reference` 和被动回复参数。

## 注意事项

- `file_info` 有时效（响应中的 `ttl`），过期需重新上传；
- 分片上传的 `md5_10m` 是文件前 `10002432` 字节的 MD5，不是整个文件；
- 上传接口超时建议不低于 5 秒，库默认使用 `max(HTTPConfig.timeout, 10)`；
- 单聊文件和群聊文件不能混用；
- URL 上传依赖平台下载，失败时优先改用 `upload_file`；
- 素材上传接口有独立频率限制，库已配置路由桶；
- 平台会校验图片实际可用性，1×1 等边界尺寸可能返回 `40034002 富媒体文件格式不支持`，使用常规尺寸的合法 PNG/JPEG 即可。 
