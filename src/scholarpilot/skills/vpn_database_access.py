"""
VPN 数据库访问 Skill - 统一的 VPN 数据库搜索和下载接口。"""
VPN 数据库访问 Skill - 统一的 VPN 数据库搜索和下载接口。

支持 10 个 VPN 可达数据库，按访问方式分为三类：
  A"""
VPN 数据库访问 Skill - 统一的 VPN 数据库搜索和下载接口。

支持 10 个 VPN 可达数据库，按访问方式分为三类：
  A. 直接 HTTP 搜索: Springer, CNKI(已有基础)
  B. 浏览器自动化: EPS, RESSET, CSMAR, CNKI数据平台
  C. 需要认证: 微观经济数据(API Token), EBSCO("""
VPN 数据库访问 Skill - 统一的 VPN 数据库搜索和下载接口。

支持 10 个 VPN 可达数据库，按访问方式分为三类：
  A. 直接 HTTP 搜索: Springer, CNKI(已有基础)
  B. 浏览器自动化: EPS, RESSET, CSMAR, CNKI数据平台
  C. 需要认证: 微观经济数据(API Token), EBSCO(SSO), WOS(SSO)

Usage:
    from scholarpilot.skills"""
VPN 数据库访问 Skill - 统一的 VPN 数据库搜索和下载接口。

支持 10 个 VPN 可达数据库，按访问方式分为三类：
  A. 直接 HTTP 搜索: Springer, CNKI(已有基础)
  B. 浏览器自动化: EPS, RESSET, CSMAR, CNKI数据平台
  C. 需要认证: 微观经济数据(API Token), EBSCO(SSO), WOS(SSO)

Usage:
    from scholarpilot.skills.vpn_database_access import VpnDatabaseAccess
    
    async with VpnDatabaseAccess()"""
VPN 数据库访问 Skill - 统一的 VPN 数据库搜索和下载接口。

支持 10 个 VPN 可达数据库，按访问方式分为三类：
  A. 直接 HTTP 搜索: Springer, CNKI(已有基础)
  B. 浏览器自动化: EPS, RESSET, CSMAR, CNKI数据平台
  C. 需要认证: 微观经济数据(API Token), EBSCO(SSO), WOS(SSO)

Usage:
    from scholarpilot.skills.vpn_database_access import VpnDatabaseAccess
    
    async with VpnDatabaseAccess() as vda:
        # 1. 搜索文献
        papers = await vda.search"""
VPN 数据库访问 Skill - 统一的 VPN 数据库搜索和下载接口。

支持 10 个 VPN 可达数据库，按访问方式分为三类：
  A. 直接 HTTP 搜索: Springer, CNKI(已有基础)
  B. 浏览器自动化: EPS, RESSET, CSMAR, CNKI数据平台
  C. 需要认证: 微观经济数据(API Token), EBSCO(SSO), WOS(SSO)

Usage:
    from scholarpilot.skills.vpn_database_access import VpnDatabaseAccess
    
    async with VpnDatabaseAccess() as vda:
        # 1. 搜索文献
        papers = await vda.search_literature("财政政策 经济增长", sources=["cnki", "springer"])
        
        #"""
VPN 数据库访问 Skill - 统一的 VPN 数据库搜索和下载接口。

支持 10 个 VPN 可达数据库，按访问方式分为三类：
  A. 直接 HTTP 搜索: Springer, CNKI(已有基础)
  B. 浏览器自动化: EPS, RESSET, CSMAR, CNKI数据平台
  C. 需要认证: 微观经济数据(API Token), EBSCO(SSO), WOS(SSO)

Usage:
    from scholarpilot.skills.vpn_database_access import VpnDatabaseAccess
    
    async with VpnDatabaseAccess() as vda:
        # 1. 搜索文献
        papers = await vda.search_literature("财政政策 经济增长", sources=["cnki", "springer"])
        
        # 2. 搜索数据
        indicators = await vda.search_indicators("财政支出"""
VPN 数据库访问 Skill - 统一的 VPN 数据库搜索和下载接口。

支持 10 个 VPN 可达数据库，按访问方式分为三类：
  A. 直接 HTTP 搜索: Springer, CNKI(已有基础)
  B. 浏览器自动化: EPS, RESSET, CSMAR, CNKI数据平台
  C. 需要认证: 微观经济数据(API Token), EBSCO(SSO), WOS(SSO)

Usage:
    from scholarpilot.skills.vpn_database_access import VpnDatabaseAccess
    
    async with VpnDatabaseAccess() as vda:
        # 1. 搜索文献
        papers = await vda.search_literature("财政政策 经济增长", sources=["cnki", "springer"])
        
        # 2. 搜索数据
        indicators = await vda.search_indicators("财政支出 GDP", database="cnki_data")
        
        # 3. 下载数据
        data ="""
VPN 数据库访问 Skill - 统一的 VPN 数据库搜索和下载接口。

支持 10 个 VPN 可达数据库，按访问方式分为三类：
  A. 直接 HTTP 搜索: Springer, CNKI(已有基础)
  B. 浏览器自动化: EPS, RESSET, CSMAR, CNKI数据平台
  C. 需要认证: 微观经济数据(API Token), EBSCO(SSO), WOS(SSO)

Usage:
    from scholarpilot.skills.vpn_database_access import VpnDatabaseAccess
    
    async with VpnDatabaseAccess() as vda:
        # 1. 搜索文献
        papers = await vda.search_literature("财政政策 经济增长", sources=["cnki", "springer"])
        
        # 2. 搜索数据
        indicators = await vda.search_indicators("财政支出 GDP", database="cnki_data")
        
        # 3. 下载数据
        data = await vda.download_dataset("cnki_data", "财政专题数据库", 
                                          indicators=[""""
VPN 数据库访问 Skill - 统一的 VPN 数据库搜索和下载接口。

支持 10 个 VPN 可达数据库，按访问方式分为三类：
  A. 直接 HTTP 搜索: Springer, CNKI(已有基础)
  B. 浏览器自动化: EPS, RESSET, CSMAR, CNKI数据平台
  C. 需要认证: 微观经济数据(API Token), EBSCO(SSO), WOS(SSO)

Usage:
    from scholarpilot.skills.vpn_database_access import VpnDatabaseAccess
    
    async with VpnDatabaseAccess() as vda:
        # 1. 搜索文献
        papers = await vda.search_literature("财政政策 经济增长", sources=["cnki", "springer"])
        
        # 2. 搜索数据
        indicators = await vda.search_indicators("财政支出 GDP", database="cnki_data")
        
        # 3. 下载数据
        data = await vda.download_dataset("cnki_data", "财政专题数据库", 
                                          indicators=["财政支出", "GDP"],
                                          regions=["北京", "上海", "广东"],
                                          years=range(2010, 2024))
"""

import asyncio
import json"""
VPN 数据库访问 Skill - 统一的 VPN 数据库搜索和下载接口。

支持 10 个 VPN 可达数据库，按访问方式分为三类：
  A. 直接 HTTP 搜索: Springer, CNKI(已有基础)
  B. 浏览器自动化: EPS, RESSET, CSMAR, CNKI数据平台
  C. 需要认证: 微观经济数据(API Token), EBSCO(SSO), WOS(SSO)

Usage:
    from scholarpilot.skills.vpn_database_access import VpnDatabaseAccess
    
    async with VpnDatabaseAccess() as vda:
        # 1. 搜索文献
        papers = await vda.search_literature("财政政策 经济增长", sources=["cnki", "springer"])
        
        # 2. 搜索数据
        indicators = await vda.search_indicators("财政支出 GDP", database="cnki_data")
        
        # 3. 下载数据
        data = await vda.download_dataset("cnki_data", "财政专题数据库", 
                                          indicators=["财政支出", "GDP"],
                                          regions=["北京", "上海", "广东"],
                                          years=range(2010, 2024))
"""

import asyncio
import json
import re
import time
from pathlib import Path
from datetime import datetime
from typing"""
VPN 数据库访问 Skill - 统一的 VPN 数据库搜索和下载接口。

支持 10 个 VPN 可达数据库，按访问方式分为三类：
  A. 直接 HTTP 搜索: Springer, CNKI(已有基础)
  B. 浏览器自动化: EPS, RESSET, CSMAR, CNKI数据平台
  C. 需要认证: 微观经济数据(API Token), EBSCO(SSO), WOS(SSO)

Usage:
    from scholarpilot.skills.vpn_database_access import VpnDatabaseAccess
    
    async with VpnDatabaseAccess() as vda:
        # 1. 搜索文献
        papers = await vda.search_literature("财政政策 经济增长", sources=["cnki", "springer"])
        
        # 2. 搜索数据
        indicators = await vda.search_indicators("财政支出 GDP", database="cnki_data")
        
        # 3. 下载数据
        data = await vda.download_dataset("cnki_data", "财政专题数据库", 
                                          indicators=["财政支出", "GDP"],
                                          regions=["北京", "上海", "广东"],
                                          years=range(2010, 2024))
"""

import asyncio
import json
import re
import time
from pathlib import Path
from datetime import datetime
from typing import Optional
from dataclasses import dataclass, field, asdict

impo"""
VPN 数据库访问 Skill - 统一的 VPN 数据库搜索和下载接口。

支持 10 个 VPN 可达数据库，按访问方式分为三类：
  A. 直接 HTTP 搜索: Springer, CNKI(已有基础)
  B. 浏览器自动化: EPS, RESSET, CSMAR, CNKI数据平台
  C. 需要认证: 微观经济数据(API Token), EBSCO(SSO), WOS(SSO)

Usage:
    from scholarpilot.skills.vpn_database_access import VpnDatabaseAccess
    
    async with VpnDatabaseAccess() as vda:
        # 1. 搜索文献
        papers = await vda.search_literature("财政政策 经济增长", sources=["cnki", "springer"])
        
        # 2. 搜索数据
        indicators = await vda.search_indicators("财政支出 GDP", database="cnki_data")
        
        # 3. 下载数据
        data = await vda.download_dataset("cnki_data", "财政专题数据库", 
                                          indicators=["财政支出", "GDP"],
                                          regions=["北京", "上海", "广东"],
                                          years=range(2010, 2024))
"""

import asyncio
import json
import re
import time
from pathlib import Path
from datetime import datetime
from typing import Optional
from dataclasses import dataclass, field, asdict

import httpx
from bs4 import BeautifulSoup

from ..utils.network import configure_no_pro"""
VPN 数据库访问 Skill - 统一的 VPN 数据库搜索和下载接口。

支持 10 个 VPN 可达数据库，按访问方式分为三类：
  A. 直接 HTTP 搜索: Springer, CNKI(已有基础)
  B. 浏览器自动化: EPS, RESSET, CSMAR, CNKI数据平台
  C. 需要认证: 微观经济数据(API Token), EBSCO(SSO), WOS(SSO)

Usage:
    from scholarpilot.skills.vpn_database_access import VpnDatabaseAccess
    
    async with VpnDatabaseAccess() as vda:
        # 1. 搜索文献
        papers = await vda.search_literature("财政政策 经济增长", sources=["cnki", "springer"])
        
        # 2. 搜索数据
        indicators = await vda.search_indicators("财政支出 GDP", database="cnki_data")
        
        # 3. 下载数据
        data = await vda.download_dataset("cnki_data", "财政专题数据库", 
                                          indicators=["财政支出", "GDP"],
                                          regions=["北京", "上海", "广东"],
                                          years=range(2010, 2024))
"""

import asyncio
import json
import re
import time
from pathlib import Path
from datetime import datetime
from typing import Optional
from dataclasses import dataclass, field, asdict

import httpx
from bs4 import BeautifulSoup

from ..utils.network import configure_no_proxy
from ..utils.vpn import check_vpn_status


# ============================================================
#"""
VPN 数据库访问 Skill - 统一的 VPN 数据库搜索和下载接口。

支持 10 个 VPN 可达数据库，按访问方式分为三类：
  A. 直接 HTTP 搜索: Springer, CNKI(已有基础)
  B. 浏览器自动化: EPS, RESSET, CSMAR, CNKI数据平台
  C. 需要认证: 微观经济数据(API Token), EBSCO(SSO), WOS(SSO)

Usage:
    from scholarpilot.skills.vpn_database_access import VpnDatabaseAccess
    
    async with VpnDatabaseAccess() as vda:
        # 1. 搜索文献
        papers = await vda.search_literature("财政政策 经济增长", sources=["cnki", "springer"])
        
        # 2. 搜索数据
        indicators = await vda.search_indicators("财政支出 GDP", database="cnki_data")
        
        # 3. 下载数据
        data = await vda.download_dataset("cnki_data", "财政专题数据库", 
                                          indicators=["财政支出", "GDP"],
                                          regions=["北京", "上海", "广东"],
                                          years=range(2010, 2024))
"""

import asyncio
import json
import re
import time
from pathlib import Path
from datetime import datetime
from typing import Optional
from dataclasses import dataclass, field, asdict

import httpx
from bs4 import BeautifulSoup

from ..utils.network import configure_no_proxy
from ..utils.vpn import check_vpn_status


# ============================================================
# 数据库配置
# ============================================================

@dataclass
class DatabaseConfig:
    """数据库配置."""
    key: str
    name: str
    url: s"""
VPN 数据库访问 Skill - 统一的 VPN 数据库搜索和下载接口。

支持 10 个 VPN 可达数据库，按访问方式分为三类：
  A. 直接 HTTP 搜索: Springer, CNKI(已有基础)
  B. 浏览器自动化: EPS, RESSET, CSMAR, CNKI数据平台
  C. 需要认证: 微观经济数据(API Token), EBSCO(SSO), WOS(SSO)

Usage:
    from scholarpilot.skills.vpn_database_access import VpnDatabaseAccess
    
    async with VpnDatabaseAccess() as vda:
        # 1. 搜索文献
        papers = await vda.search_literature("财政政策 经济增长", sources=["cnki", "springer"])
        
        # 2. 搜索数据
        indicators = await vda.search_indicators("财政支出 GDP", database="cnki_data")
        
        # 3. 下载数据
        data = await vda.download_dataset("cnki_data", "财政专题数据库", 
                                          indicators=["财政支出", "GDP"],
                                          regions=["北京", "上海", "广东"],
                                          years=range(2010, 2024))
"""

import asyncio
import json
import re
import time
from pathlib import Path
from datetime import datetime
from typing import Optional
from dataclasses import dataclass, field, asdict

import httpx
from bs4 import BeautifulSoup

from ..utils.network import configure_no_proxy
from ..utils.vpn import check_vpn_status


# ============================================================
# 数据库配置
# ============================================================

@dataclass
class DatabaseConfig:
    """数据库配置."""
    key: str
    name: str
    url: str
    category: str  # 文献/数据
    access_method: str  # direc"""
VPN 数据库访问 Skill - 统一的 VPN 数据库搜索和下载接口。

支持 10 个 VPN 可达数据库，按访问方式分为三类：
  A. 直接 HTTP 搜索: Springer, CNKI(已有基础)
  B. 浏览器自动化: EPS, RESSET, CSMAR, CNKI数据平台
  C. 需要认证: 微观经济数据(API Token), EBSCO(SSO), WOS(SSO)

Usage:
    from scholarpilot.skills.vpn_database_access import VpnDatabaseAccess
    
    async with VpnDatabaseAccess() as vda:
        # 1. 搜索文献
        papers = await vda.search_literature("财政政策 经济增长", sources=["cnki", "springer"])
        
        # 2. 搜索数据
        indicators = await vda.search_indicators("财政支出 GDP", database="cnki_data")
        
        # 3. 下载数据
        data = await vda.download_dataset("cnki_data", "财政专题数据库", 
                                          indicators=["财政支出", "GDP"],
                                          regions=["北京", "上海", "广东"],
                                          years=range(2010, 2024))
"""

import asyncio
import json
import re
import time
from pathlib import Path
from datetime import datetime
from typing import Optional
from dataclasses import dataclass, field, asdict

import httpx
from bs4 import BeautifulSoup

from ..utils.network import configure_no_proxy
from ..utils.vpn import check_vpn_status


# ============================================================
# 数据库配置
# ============================================================

@dataclass
class DatabaseConfig:
    """数据库配置."""
    key: str
    name: str
    url: str
    category: str  # 文献/数据
    access_method: str  # direct_http / browser / api / sso
    search_endpoint: Optional[str] = Non"""
VPN 数据库访问 Skill - 统一的 VPN 数据库搜索和下载接口。

支持 10 个 VPN 可达数据库，按访问方式分为三类：
  A. 直接 HTTP 搜索: Springer, CNKI(已有基础)
  B. 浏览器自动化: EPS, RESSET, CSMAR, CNKI数据平台
  C. 需要认证: 微观经济数据(API Token), EBSCO(SSO), WOS(SSO)

Usage:
    from scholarpilot.skills.vpn_database_access import VpnDatabaseAccess
    
    async with VpnDatabaseAccess() as vda:
        # 1. 搜索文献
        papers = await vda.search_literature("财政政策 经济增长", sources=["cnki", "springer"])
        
        # 2. 搜索数据
        indicators = await vda.search_indicators("财政支出 GDP", database="cnki_data")
        
        # 3. 下载数据
        data = await vda.download_dataset("cnki_data", "财政专题数据库", 
                                          indicators=["财政支出", "GDP"],
                                          regions=["北京", "上海", "广东"],
                                          years=range(2010, 2024))
"""

import asyncio
import json
import re
import time
from pathlib import Path
from datetime import datetime
from typing import Optional
from dataclasses import dataclass, field, asdict

import httpx
from bs4 import BeautifulSoup

from ..utils.network import configure_no_proxy
from ..utils.vpn import check_vpn_status


# ============================================================
# 数据库配置
# ============================================================

@dataclass
class DatabaseConfig:
    """数据库配置."""
    key: str
    name: str
    url: str
    category: str  # 文献/数据
    access_method: str  # direct_http / browser / api / sso
    search_endpoint: Optional[str] = None
    search_params: dict = field(default_factory=dict)
    auth_required: bool"""
VPN 数据库访问 Skill - 统一的 VPN 数据库搜索和下载接口。

支持 10 个 VPN 可达数据库，按访问方式分为三类：
  A. 直接 HTTP 搜索: Springer, CNKI(已有基础)
  B. 浏览器自动化: EPS, RESSET, CSMAR, CNKI数据平台
  C. 需要认证: 微观经济数据(API Token), EBSCO(SSO), WOS(SSO)

Usage:
    from scholarpilot.skills.vpn_database_access import VpnDatabaseAccess
    
    async with VpnDatabaseAccess() as vda:
        # 1. 搜索文献
        papers = await vda.search_literature("财政政策 经济增长", sources=["cnki", "springer"])
        
        # 2. 搜索数据
        indicators = await vda.search_indicators("财政支出 GDP", database="cnki_data")
        
        # 3. 下载数据
        data = await vda.download_dataset("cnki_data", "财政专题数据库", 
                                          indicators=["财政支出", "GDP"],
                                          regions=["北京", "上海", "广东"],
                                          years=range(2010, 2024))
"""

import asyncio
import json
import re
import time
from pathlib import Path
from datetime import datetime
from typing import Optional
from dataclasses import dataclass, field, asdict

import httpx
from bs4 import BeautifulSoup

from ..utils.network import configure_no_proxy
from ..utils.vpn import check_vpn_status


# ============================================================
# 数据库配置
# ============================================================

@dataclass
class DatabaseConfig:
    """数据库配置."""
    key: str
    name: str
    url: str
    category: str  # 文献/数据
    access_method: str  # direct_http / browser / api / sso
    search_endpoint: Optional[str] = None
    search_params: dict = field(default_factory=dict)
    auth_required: bool = False
    auth_type: Optional[str] = None  # none / cooki"""
VPN 数据库访问 Skill - 统一的 VPN 数据库搜索和下载接口。

支持 10 个 VPN 可达数据库，按访问方式分为三类：
  A. 直接 HTTP 搜索: Springer, CNKI(已有基础)
  B. 浏览器自动化: EPS, RESSET, CSMAR, CNKI数据平台
  C. 需要认证: 微观经济数据(API Token), EBSCO(SSO), WOS(SSO)

Usage:
    from scholarpilot.skills.vpn_database_access import VpnDatabaseAccess
    
    async with VpnDatabaseAccess() as vda:
        # 1. 搜索文献
        papers = await vda.search_literature("财政政策 经济增长", sources=["cnki", "springer"])
        
        # 2. 搜索数据
        indicators = await vda.search_indicators("财政支出 GDP", database="cnki_data")
        
        # 3. 下载数据
        data = await vda.download_dataset("cnki_data", "财政专题数据库", 
                                          indicators=["财政支出", "GDP"],
                                          regions=["北京", "上海", "广东"],
                                          years=range(2010, 2024))
"""

import asyncio
import json
import re
import time
from pathlib import Path
from datetime import datetime
from typing import Optional
from dataclasses import dataclass, field, asdict

import httpx
from bs4 import BeautifulSoup

from ..utils.network import configure_no_proxy
from ..utils.vpn import check_vpn_status


# ============================================================
# 数据库配置
# ============================================================

@dataclass
class DatabaseConfig:
    """数据库配置."""
    key: str
    name: str
    url: str
    category: str  # 文献/数据
    access_method: str  # direct_http / browser / api / sso
    search_endpoint: Optional[str] = None
    search_params: dict = field(default_factory=dict)
    auth_required: bool = False
    auth_type: Optional[str] = None  # none / cookie / token / sso
    notes: str = ""


# 数据库配置表
DB"""
VPN 数据库访问 Skill - 统一的 VPN 数据库搜索和下载接口。

支持 10 个 VPN 可达数据库，按访问方式分为三类：
  A. 直接 HTTP 搜索: Springer, CNKI(已有基础)
  B. 浏览器自动化: EPS, RESSET, CSMAR, CNKI数据平台
  C. 需要认证: 微观经济数据(API Token), EBSCO(SSO), WOS(SSO)

Usage:
    from scholarpilot.skills.vpn_database_access import VpnDatabaseAccess
    
    async with VpnDatabaseAccess() as vda:
        # 1. 搜索文献
        papers = await vda.search_literature("财政政策 经济增长", sources=["cnki", "springer"])
        
        # 2. 搜索数据
        indicators = await vda.search_indicators("财政支出 GDP", database="cnki_data")
        
        # 3. 下载数据
        data = await vda.download_dataset("cnki_data", "财政专题数据库", 
                                          indicators=["财政支出", "GDP"],
                                          regions=["北京", "上海", "广东"],
                                          years=range(2010, 2024))
"""

import asyncio
import json
import re
import time
from pathlib import Path
from datetime import datetime
from typing import Optional
from dataclasses import dataclass, field, asdict

import httpx
from bs4 import BeautifulSoup

from ..utils.network import configure_no_proxy
from ..utils.vpn import check_vpn_status


# ============================================================
# 数据库配置
# ============================================================

@dataclass
class DatabaseConfig:
    """数据库配置."""
    key: str
    name: str
    url: str
    category: str  # 文献/数据
    access_method: str  # direct_http / browser / api / sso
    search_endpoint: Optional[str] = None
    search_params: dict = field(default_factory=dict)
    auth_required: bool = False
    auth_type: Optional[str] = None  # none / cookie / token / sso
    notes: str = ""


# 数据库配置表
DB_CONFIGS: dict[str, DatabaseConfig] = {
    # === 文献类 ==="""
VPN 数据库访问 Skill - 统一的 VPN 数据库搜索和下载接口。

支持 10 个 VPN 可达数据库，按访问方式分为三类：
  A. 直接 HTTP 搜索: Springer, CNKI(已有基础)
  B. 浏览器自动化: EPS, RESSET, CSMAR, CNKI数据平台
  C. 需要认证: 微观经济数据(API Token), EBSCO(SSO), WOS(SSO)

Usage:
    from scholarpilot.skills.vpn_database_access import VpnDatabaseAccess
    
    async with VpnDatabaseAccess() as vda:
        # 1. 搜索文献
        papers = await vda.search_literature("财政政策 经济增长", sources=["cnki", "springer"])
        
        # 2. 搜索数据
        indicators = await vda.search_indicators("财政支出 GDP", database="cnki_data")
        
        # 3. 下载数据
        data = await vda.download_dataset("cnki_data", "财政专题数据库", 
                                          indicators=["财政支出", "GDP"],
                                          regions=["北京", "上海", "广东"],
                                          years=range(2010, 2024))
"""

import asyncio
import json
import re
import time
from pathlib import Path
from datetime import datetime
from typing import Optional
from dataclasses import dataclass, field, asdict

import httpx
from bs4 import BeautifulSoup

from ..utils.network import configure_no_proxy
from ..utils.vpn import check_vpn_status


# ============================================================
# 数据库配置
# ============================================================

@dataclass
class DatabaseConfig:
    """数据库配置."""
    key: str
    name: str
    url: str
    category: str  # 文献/数据
    access_method: str  # direct_http / browser / api / sso
    search_endpoint: Optional[str] = None
    search_params: dict = field(default_factory=dict)
    auth_required: bool = False
    auth_type: Optional[str] = None  # none / cookie / token / sso
    notes: str = ""


# 数据库配置表
DB_CONFIGS: dict[str, DatabaseConfig] = {
    # === 文献类 ===
    "cnki": DatabaseConfig(
        key="cnki",
        name="中国知网 CN"""
VPN 数据库访问 Skill - 统一的 VPN 数据库搜索和下载接口。

支持 10 个 VPN 可达数据库，按访问方式分为三类：
  A. 直接 HTTP 搜索: Springer, CNKI(已有基础)
  B. 浏览器自动化: EPS, RESSET, CSMAR, CNKI数据平台
  C. 需要认证: 微观经济数据(API Token), EBSCO(SSO), WOS(SSO)

Usage:
    from scholarpilot.skills.vpn_database_access import VpnDatabaseAccess
    
    async with VpnDatabaseAccess() as vda:
        # 1. 搜索文献
        papers = await vda.search_literature("财政政策 经济增长", sources=["cnki", "springer"])
        
        # 2. 搜索数据
        indicators = await vda.search_indicators("财政支出 GDP", database="cnki_data")
        
        # 3. 下载数据
        data = await vda.download_dataset("cnki_data", "财政专题数据库", 
                                          indicators=["财政支出", "GDP"],
                                          regions=["北京", "上海", "广东"],
                                          years=range(2010, 2024))
"""

import asyncio
import json
import re
import time
from pathlib import Path
from datetime import datetime
from typing import Optional
from dataclasses import dataclass, field, asdict

import httpx
from bs4 import BeautifulSoup

from ..utils.network import configure_no_proxy
from ..utils.vpn import check_vpn_status


# ============================================================
# 数据库配置
# ============================================================

@dataclass
class DatabaseConfig:
    """数据库配置."""
    key: str
    name: str
    url: str
    category: str  # 文献/数据
    access_method: str  # direct_http / browser / api / sso
    search_endpoint: Optional[str] = None
    search_params: dict = field(default_factory=dict)
    auth_required: bool = False
    auth_type: Optional[str] = None  # none / cookie / token / sso
    notes: str = ""


# 数据库配置表
DB_CONFIGS: dict[str, DatabaseConfig] = {
    # === 文献类 ===
    "cnki": DatabaseConfig(
        key="cnki",
        name="中国知网 CNKI",
        url="https://kns.cnki.net",
        category="文献","""
VPN 数据库访问 Skill - 统一的 VPN 数据库搜索和下载接口。

支持 10 个 VPN 可达数据库，按访问方式分为三类：
  A. 直接 HTTP 搜索: Springer, CNKI(已有基础)
  B. 浏览器自动化: EPS, RESSET, CSMAR, CNKI数据平台
  C. 需要认证: 微观经济数据(API Token), EBSCO(SSO), WOS(SSO)

Usage:
    from scholarpilot.skills.vpn_database_access import VpnDatabaseAccess
    
    async with VpnDatabaseAccess() as vda:
        # 1. 搜索文献
        papers = await vda.search_literature("财政政策 经济增长", sources=["cnki", "springer"])
        
        # 2. 搜索数据
        indicators = await vda.search_indicators("财政支出 GDP", database="cnki_data")
        
        # 3. 下载数据
        data = await vda.download_dataset("cnki_data", "财政专题数据库", 
                                          indicators=["财政支出", "GDP"],
                                          regions=["北京", "上海", "广东"],
                                          years=range(2010, 2024))
"""

import asyncio
import json
import re
import time
from pathlib import Path
from datetime import datetime
from typing import Optional
from dataclasses import dataclass, field, asdict

import httpx
from bs4 import BeautifulSoup

from ..utils.network import configure_no_proxy
from ..utils.vpn import check_vpn_status


# ============================================================
# 数据库配置
# ============================================================

@dataclass
class DatabaseConfig:
    """数据库配置."""
    key: str
    name: str
    url: str
    category: str  # 文献/数据
    access_method: str  # direct_http / browser / api / sso
    search_endpoint: Optional[str] = None
    search_params: dict = field(default_factory=dict)
    auth_required: bool = False
    auth_type: Optional[str] = None  # none / cookie / token / sso
    notes: str = ""


# 数据库配置表
DB_CONFIGS: dict[str, DatabaseConfig] = {
    # === 文献类 ===
    "cnki": DatabaseConfig(
        key="cnki",
        name="中国知网 CNKI",
        url="https://kns.cnki.net",
        category="文献",
        access_method="direct_http",
        search_endpoint="https://kns.cnki"""
VPN 数据库访问 Skill - 统一的 VPN 数据库搜索和下载接口。

支持 10 个 VPN 可达数据库，按访问方式分为三类：
  A. 直接 HTTP 搜索: Springer, CNKI(已有基础)
  B. 浏览器自动化: EPS, RESSET, CSMAR, CNKI数据平台
  C. 需要认证: 微观经济数据(API Token), EBSCO(SSO), WOS(SSO)

Usage:
    from scholarpilot.skills.vpn_database_access import VpnDatabaseAccess
    
    async with VpnDatabaseAccess() as vda:
        # 1. 搜索文献
        papers = await vda.search_literature("财政政策 经济增长", sources=["cnki", "springer"])
        
        # 2. 搜索数据
        indicators = await vda.search_indicators("财政支出 GDP", database="cnki_data")
        
        # 3. 下载数据
        data = await vda.download_dataset("cnki_data", "财政专题数据库", 
                                          indicators=["财政支出", "GDP"],
                                          regions=["北京", "上海", "广东"],
                                          years=range(2010, 2024))
"""

import asyncio
import json
import re
import time
from pathlib import Path
from datetime import datetime
from typing import Optional
from dataclasses import dataclass, field, asdict

import httpx
from bs4 import BeautifulSoup

from ..utils.network import configure_no_proxy
from ..utils.vpn import check_vpn_status


# ============================================================
# 数据库配置
# ============================================================

@dataclass
class DatabaseConfig:
    """数据库配置."""
    key: str
    name: str
    url: str
    category: str  # 文献/数据
    access_method: str  # direct_http / browser / api / sso
    search_endpoint: Optional[str] = None
    search_params: dict = field(default_factory=dict)
    auth_required: bool = False
    auth_type: Optional[str] = None  # none / cookie / token / sso
    notes: str = ""


# 数据库配置表
DB_CONFIGS: dict[str, DatabaseConfig] = {
    # === 文献类 ===
    "cnki": DatabaseConfig(
        key="cnki",
        name="中国知网 CNKI",
        url="https://kns.cnki.net",
        category="文献",
        access_method="direct_http",
        search_endpoint="https://kns.cnki.net/kns8s/Brief/GetGridTableHtml",
        search_params={"IsSearch"""
VPN 数据库访问 Skill - 统一的 VPN 数据库搜索和下载接口。

支持 10 个 VPN 可达数据库，按访问方式分为三类：
  A. 直接 HTTP 搜索: Springer, CNKI(已有基础)
  B. 浏览器自动化: EPS, RESSET, CSMAR, CNKI数据平台
  C. 需要认证: 微观经济数据(API Token), EBSCO(SSO), WOS(SSO)

Usage:
    from scholarpilot.skills.vpn_database_access import VpnDatabaseAccess
    
    async with VpnDatabaseAccess() as vda:
        # 1. 搜索文献
        papers = await vda.search_literature("财政政策 经济增长", sources=["cnki", "springer"])
        
        # 2. 搜索数据
        indicators = await vda.search_indicators("财政支出 GDP", database="cnki_data")
        
        # 3. 下载数据
        data = await vda.download_dataset("cnki_data", "财政专题数据库", 
                                          indicators=["财政支出", "GDP"],
                                          regions=["北京", "上海", "广东"],
                                          years=range(2010, 2024))
"""

import asyncio
import json
import re
import time
from pathlib import Path
from datetime import datetime
from typing import Optional
from dataclasses import dataclass, field, asdict

import httpx
from bs4 import BeautifulSoup

from ..utils.network import configure_no_proxy
from ..utils.vpn import check_vpn_status


# ============================================================
# 数据库配置
# ============================================================

@dataclass
class DatabaseConfig:
    """数据库配置."""
    key: str
    name: str
    url: str
    category: str  # 文献/数据
    access_method: str  # direct_http / browser / api / sso
    search_endpoint: Optional[str] = None
    search_params: dict = field(default_factory=dict)
    auth_required: bool = False
    auth_type: Optional[str] = None  # none / cookie / token / sso
    notes: str = ""


# 数据库配置表
DB_CONFIGS: dict[str, DatabaseConfig] = {
    # === 文献类 ===
    "cnki": DatabaseConfig(
        key="cnki",
        name="中国知网 CNKI",
        url="https://kns.cnki.net",
        category="文献",
        access_method="direct_http",
        search_endpoint="https://kns.cnki.net/kns8s/Brief/GetGridTableHtml",
        search_params={"IsSearch": "true", "PageName": "ASP.brief_result_aspx"},
        auth_"""
VPN 数据库访问 Skill - 统一的 VPN 数据库搜索和下载接口。

支持 10 个 VPN 可达数据库，按访问方式分为三类：
  A. 直接 HTTP 搜索: Springer, CNKI(已有基础)
  B. 浏览器自动化: EPS, RESSET, CSMAR, CNKI数据平台
  C. 需要认证: 微观经济数据(API Token), EBSCO(SSO), WOS(SSO)

Usage:
    from scholarpilot.skills.vpn_database_access import VpnDatabaseAccess
    
    async with VpnDatabaseAccess() as vda:
        # 1. 搜索文献
        papers = await vda.search_literature("财政政策 经济增长", sources=["cnki", "springer"])
        
        # 2. 搜索数据
        indicators = await vda.search_indicators("财政支出 GDP", database="cnki_data")
        
        # 3. 下载数据
        data = await vda.download_dataset("cnki_data", "财政专题数据库", 
                                          indicators=["财政支出", "GDP"],
                                          regions=["北京", "上海", "广东"],
                                          years=range(2010, 2024))
"""

import asyncio
import json
import re
import time
from pathlib import Path
from datetime import datetime
from typing import Optional
from dataclasses import dataclass, field, asdict

import httpx
from bs4 import BeautifulSoup

from ..utils.network import configure_no_proxy
from ..utils.vpn import check_vpn_status


# ============================================================
# 数据库配置
# ============================================================

@dataclass
class DatabaseConfig:
    """数据库配置."""
    key: str
    name: str
    url: str
    category: str  # 文献/数据
    access_method: str  # direct_http / browser / api / sso
    search_endpoint: Optional[str] = None
    search_params: dict = field(default_factory=dict)
    auth_required: bool = False
    auth_type: Optional[str] = None  # none / cookie / token / sso
    notes: str = ""


# 数据库配置表
DB_CONFIGS: dict[str, DatabaseConfig] = {
    # === 文献类 ===
    "cnki": DatabaseConfig(
        key="cnki",
        name="中国知网 CNKI",
        url="https://kns.cnki.net",
        category="文献",
        access_method="direct_http",
        search_endpoint="https://kns.cnki.net/kns8s/Brief/GetGridTableHtml",
        search_params={"IsSearch": "true", "PageName": "ASP.brief_result_aspx"},
        auth_required=True,
        auth_type="cookie",
        notes="已集成 aiohttp_engin