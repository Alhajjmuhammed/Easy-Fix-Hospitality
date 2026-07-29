from django.db import models
import os


class MobileAppRelease(models.Model):
    version = models.CharField(max_length=30)
    apk_file = models.FileField(upload_to='apk/')
    release_notes = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"v{self.version}"

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if self.is_active:
            # Only one release is active at a time
            MobileAppRelease.objects.exclude(pk=self.pk).update(is_active=False)

    def delete_apk_file(self):
        if self.apk_file and os.path.isfile(self.apk_file.path):
            os.remove(self.apk_file.path)
