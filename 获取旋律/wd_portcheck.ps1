param([int]$port = 17865)
try {
  $c = New-Object Net.Sockets.TcpClient('127.0.0.1', $port)
  $c.Close()
  exit 0
} catch {
  exit 1
}
