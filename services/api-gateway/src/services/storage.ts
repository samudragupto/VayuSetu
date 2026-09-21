import { Storage } from "@google-cloud/storage";

import { withRetry } from "../lib/retry";
import type { Logger } from "../logger";

export interface UploadRequest {
  reportId: string;
  phoneHash: string;
  messageSid: string;
  contentType: string;
  body: Buffer;
  receivedAt: Date;
}

export interface UploadResult {
  bucket: string;
  objectName: string;
  gsUri: string;
  sizeBytes: number;
}

export interface ImageStore {
  buildObjectName(reportId: string, contentType: string, receivedAt: Date): string;
  upload(request: UploadRequest): Promise<UploadResult>;
}

const EXTENSIONS: Record<string, string> = {
  "image/jpeg": "jpg",
  "image/jpg": "jpg",
  "image/png": "png",
  "image/webp": "webp",
  "image/heic": "heic",
  "image/heif": "heif",
};

export function extensionFor(contentType: string): string {
  return EXTENSIONS[contentType.toLowerCase().split(";")[0]?.trim() ?? ""] ?? "bin";
}

export function isSupportedImage(contentType: string | undefined | null): boolean {
  if (!contentType) {
    return false;
  }
  return Object.prototype.hasOwnProperty.call(EXTENSIONS, contentType.toLowerCase().split(";")[0]?.trim() ?? "");
}

/**
 * Uploads citizen images to Cloud Storage. The object is written with custom
 * metadata carrying the Firestore report identifier so the vision function
 * can correlate the object finalize event with the report document.
 */
export class GcsImageStore implements ImageStore {
  constructor(
    private readonly storage: Storage,
    private readonly bucketName: string,
    private readonly prefix: string,
    private readonly logger: Logger
  ) {}

  buildObjectName(reportId: string, contentType: string, receivedAt: Date): string {
    const yyyy = receivedAt.getUTCFullYear().toString();
    const mm = (receivedAt.getUTCMonth() + 1).toString().padStart(2, "0");
    const dd = receivedAt.getUTCDate().toString().padStart(2, "0");
    const cleanPrefix = this.prefix.replace(/^\/+|\/+$/g, "") || "reports";
    return `${cleanPrefix}/${yyyy}/${mm}/${dd}/${reportId}.${extensionFor(contentType)}`;
  }

  async upload(request: UploadRequest): Promise<UploadResult> {
    const objectName = this.buildObjectName(request.reportId, request.contentType, request.receivedAt);
    const file = this.storage.bucket(this.bucketName).file(objectName);

    await withRetry(
      async () => {
        await file.save(request.body, {
          resumable: false,
          contentType: request.contentType,
          metadata: {
            cacheControl: "private, max-age=0",
            metadata: {
              reportId: request.reportId,
              phoneHash: request.phoneHash,
              messageSid: request.messageSid,
              source: "whatsapp",
              receivedAt: request.receivedAt.toISOString(),
            },
          },
        });
      },
      {
        attempts: 4,
        onRetry: (error, attempt, delayMs) =>
          this.logger.warn({ err: error, attempt, delayMs, objectName }, "Retrying Cloud Storage upload"),
      }
    );

    return {
      bucket: this.bucketName,
      objectName,
      gsUri: `gs://${this.bucketName}/${objectName}`,
      sizeBytes: request.body.byteLength,
    };
  }
}

export function createStorage(projectId: string): Storage {
  return new Storage({ projectId });
}
