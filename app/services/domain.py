import dns.resolver

from config import Settings


class DomainService:
    def __init__(self, settings: Settings):
        self.server_ip = settings.server_ip

    async def verify_domain(
        self, hostname: str, project_id: str
    ) -> tuple[bool, str, str | None]:
        try:
            a_records = dns.resolver.resolve(hostname, "A")
            a_record_ip = str(a_records[0])

            if a_record_ip != self.server_ip:
                return (
                    False,
                    "A record mismatch",
                    f"A record points to {a_record_ip}, expected {self.server_ip}",
                )

            txt_records = dns.resolver.resolve(f"_devpush.{hostname}", "TXT")
            txt_record = str(txt_records[0]).strip('"')

            if txt_record != f"devpush-verify={hostname},{project_id}":
                return (
                    False,
                    "TXT record mismatch",
                    f'TXT record contains "{txt_record}", expected "devpush-verify={hostname},{project_id}"',
                )

            return True, "Domain verified successfully", None

        except Exception as e:
            return False, "Verification failed", str(e)
