# R003 · nginx parado

**Alerta:** `Service nginx is not running` no Zabbix.
**Uso no experimento:** procedimento executado de memória; este documento é referência.

## 1. Conferir o estado

```bash
systemctl status nginx
```

Se o status mostrar erro de configuração, porta ou permissão, investigar antes de subir o serviço
(por exemplo, `journalctl -u nginx -n 20 --no-pager` e `nginx -t`).

## 2. Subir o serviço

Estado `inactive`:

```bash
systemctl start nginx
```

Estado `failed`, sem erro conhecido:

```bash
systemctl restart nginx
```

## 3. Confirmar

```bash
systemctl status nginx
```

Deve mostrar `active (running)`. Em seguida, conferir no Zabbix que o problema fechou.
