import asyncio
import ssl
import sys
import logging

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

async def handle_client(reader, writer):
    cert = writer.get_extra_info('peercert')
    tenant_id = dict(x[0] for x in cert['subject'])['commonName']
    logging.info(f"mTLS Connection Accepted from: {tenant_id}")
    
    data = await reader.read(1024)
    message = data.decode()
    logging.info(f"Data Received: {message}")
    
    writer.write(b"ACK: Data received securely\n")
    await writer.drain()
    writer.close()

async def main():
    # ==========================================
    # mTLS Configuration (SSLContext)
    # ==========================================
    context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    context.load_cert_chain(certfile='config/certs/server.pem', keyfile='config/certs/server.key')
    context.load_verify_locations(cafile='config/certs/ca.pem')
    
    context.verify_mode = ssl.CERT_REQUIRED 

    # ==========================================
    #  Integration with Systemd Socket Activation
    # ==========================================
    import socket
    sock = socket.fromfd(3, socket.AF_INET, socket.SOCK_STREAM)
    
    server = await asyncio.start_server(handle_client, sock=sock, ssl=context)
    logging.info(" Cerberus Gateway running and listening via Systemd...")
    
    async with server:
        await server.serve_forever()

if __name__ == "__main__":
    asyncio.run(main())
