"""ClamAV integration - Virus scanning.

Implements IVirusScanner protocol using clamd TCP socket for:
- Pre-publication malware scanning
- Configurable scan timeout
- Clear success/failure status codes
"""
