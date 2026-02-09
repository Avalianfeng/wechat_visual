"""联系人到用户映射模块

职责：
- 管理微信联系人到系统用户ID的映射关系
- 支持配置文件和数据库两种方式
- 处理默认用户映射

设计原则：
- 配置文件优先，数据库作为扩展（未来）
- 默认用户映射：如果没有配置，使用默认用户ID
- 日志记录所有映射操作
"""

import json
import logging
import os
from pathlib import Path
from typing import Optional, Dict, List
from dataclasses import dataclass, asdict

# 支持相对导入和绝对导入
try:
    from .config import WeChatAutomationConfig
except ImportError:
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent))
    from config import WeChatAutomationConfig

logger = logging.getLogger(__name__)

# 全局单例实例（延迟初始化）
_global_mapper_instance: Optional['ContactUserMapper'] = None


@dataclass
class ContactMapping:
    """联系人映射信息"""
    contact_name: str
    user_id: int
    contact_id: Optional[str] = None  # 联系人ID（可选）


class ContactUserMapper:
    """联系人到用户映射器
    
    职责：
    - 管理联系人映射关系
    - 从配置文件加载映射
    - 支持添加、查询、更新映射
    """
    
    def __init__(self, config_file: Optional[Path] = None):
        """
        初始化映射器
        
        Args:
            config_file: 配置文件路径，如果为None则使用默认路径
        """
        # 配置文件路径
        if config_file is None:
            config_dir = WeChatAutomationConfig.BASE_DIR
            config_file = config_dir / "contact_config.json"
        
        self.config_file = Path(config_file)
        logger.debug(f"[ContactUserMapper] 初始化映射器，配置文件: {self.config_file}")
        
        # 映射数据：{contact_name: ContactMapping}
        self._mappings: Dict[str, ContactMapping] = {}
        
        # 默认用户ID（如果没有配置映射，使用此ID）
        # 说明：2026-02 起，配置文件中不再存储 default_user_id 字段，
        # 只在代码中保留一个固定的回退值，用于未配置联系人的兜底逻辑。
        self.default_user_id: int = 0
        
        # 启用的联系人列表（空列表表示所有联系人）
        self.enabled_contacts: List[str] = []

        # 通过环境变量配置的“我”联系人名称（可选）
        # 环境变量名：WECHAT_ME_CONTACT 或 WECHAT_ME_CONTACT_NAME（前者优先）
        self.me_contact_name: Optional[str] = None
        
        # 加载配置
        self._load_config()
        # 加载“我”联系人配置
        self._load_me_contact_from_env()
        logger.debug(
            f"[ContactUserMapper] 映射器初始化完成，已加载 {len(self._mappings)} 个映射"
            + (f"，me_contact={self.me_contact_name!r}" if self.me_contact_name else "")
        )
    
    def _load_config(self) -> None:
        """
        从配置文件加载映射关系
        
        配置文件格式：
        {
            "contact_mappings": {
                "联系人名称1": {
                    "user_id": 1,
                    "contact_id": "optional_id"
                },
                "联系人名称2": 2  // 简化格式，直接是user_id
            },
            "enabled_contacts": ["联系人1", "联系人2"]  // 空列表表示所有联系人
        }
        """
        logger.debug(f"[ContactUserMapper] 开始加载配置文件: {self.config_file}")
        
        # 如果配置文件不存在，创建默认配置
        if not self.config_file.exists():
            logger.warning(f"[ContactUserMapper] 配置文件不存在，创建默认配置: {self.config_file}")
            self._create_default_config()
            return
        
        try:
            # 读取配置文件
            with open(self.config_file, 'r', encoding='utf-8') as f:
                config_data = json.load(f)
            
            logger.debug(f"[ContactUserMapper] 配置文件加载成功")
            
            # 加载启用的联系人列表（default_user_id 已弃用，不再从配置中读取）
            self.enabled_contacts = config_data.get("enabled_contacts", [])
            if self.enabled_contacts:
                logger.debug(f"[ContactUserMapper] 启用的联系人: {self.enabled_contacts}")
            else:
                logger.debug(f"[ContactUserMapper] 所有联系人均启用（enabled_contacts为空）")
            
            # 加载映射关系
            contact_mappings = config_data.get("contact_mappings", {})
            logger.debug(f"[ContactUserMapper] 开始加载 {len(contact_mappings)} 个映射关系")
            
            for contact_name, mapping_data in contact_mappings.items():
                try:
                    if isinstance(mapping_data, dict):
                        # 完整格式：{"user_id": 1, "contact_id": "optional"}
                        user_id = mapping_data.get("user_id")
                        contact_id = mapping_data.get("contact_id")
                    elif isinstance(mapping_data, int):
                        # 简化格式：直接是user_id
                        user_id = mapping_data
                        contact_id = None
                    else:
                        logger.error(f"[ContactUserMapper] 无效的映射格式: {contact_name} -> {mapping_data}")
                        continue
                    
                    if user_id is None:
                        logger.error(f"[ContactUserMapper] 映射缺少user_id: {contact_name}")
                        continue
                    
                    mapping = ContactMapping(
                        contact_name=contact_name,
                        user_id=int(user_id),
                        contact_id=str(contact_id) if contact_id else None
                    )
                    
                    self._mappings[contact_name] = mapping
                    logger.debug(f"[ContactUserMapper] ✓ 加载映射: {contact_name} -> 用户ID {mapping.user_id}" + 
                              (f" (联系人ID: {mapping.contact_id})" if mapping.contact_id else ""))
                    
                except Exception as e:
                    logger.error(f"[ContactUserMapper] ✗ 加载映射失败: {contact_name} -> {mapping_data}, 错误: {e}")
                    continue
            
            logger.debug(f"[ContactUserMapper] 配置加载完成，共 {len(self._mappings)} 个映射")
            
        except json.JSONDecodeError as e:
            logger.error(f"[ContactUserMapper] ✗ 配置文件JSON格式错误: {e}")
            logger.error(f"[ContactUserMapper] 将使用默认配置")
            self._create_default_config()
        except Exception as e:
            logger.error(f"[ContactUserMapper] ✗ 加载配置文件失败: {e}")
            logger.error(f"[ContactUserMapper] 将使用默认配置")
            self._create_default_config()
    
    def _create_default_config(self) -> None:
        """创建默认配置文件"""
        logger.info(f"[ContactUserMapper] 创建默认配置文件")
        
        default_config = {
            "contact_mappings": {},
            "enabled_contacts": []
        }
        
        try:
            # 确保目录存在
            self.config_file.parent.mkdir(parents=True, exist_ok=True)
            
            # 写入默认配置
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(default_config, f, ensure_ascii=False, indent=2)
            
            logger.info(f"[ContactUserMapper] ✓ 默认配置文件创建成功: {self.config_file}")
        except Exception as e:
            logger.error(f"[ContactUserMapper] ✗ 创建默认配置文件失败: {e}")
            # 即使创建失败，也继续使用内存中的默认值
    
    def get_user_id(self, contact_name: str) -> int:
        """
        获取联系人对应的用户ID
        
        Args:
            contact_name: 联系人名称
        
        Returns:
            用户ID，如果未配置则返回默认用户ID
        """
        logger.debug(f"[ContactUserMapper] 查询联系人映射: {contact_name}")
        
        if contact_name in self._mappings:
            mapping = self._mappings[contact_name]
            logger.debug(f"[ContactUserMapper] ✓ 找到映射: {contact_name} -> 用户ID {mapping.user_id}")
            return mapping.user_id
        
        logger.debug(f"[ContactUserMapper] 未找到映射，使用默认用户ID: {self.default_user_id} (联系人: {contact_name})")
        return self.default_user_id
    
    def get_contact_id(self, contact_name: str) -> Optional[str]:
        """
        获取联系人的ID（可选）
        
        Args:
            contact_name: 联系人名称
        
        Returns:
            联系人ID，如果未配置则返回None
        """
        if contact_name in self._mappings:
            return self._mappings[contact_name].contact_id
        return None
    
    def set_mapping(self, contact_name: str, user_id: int, contact_id: Optional[str] = None) -> bool:
        """
        设置联系人映射关系
        
        Args:
            contact_name: 联系人名称
            user_id: 用户ID
            contact_id: 联系人ID（可选）
        
        Returns:
            是否设置成功
        """
        logger.info(f"[ContactUserMapper] 设置映射: {contact_name} -> 用户ID {user_id}" + 
                   (f" (联系人ID: {contact_id})" if contact_id else ""))
        
        try:
            mapping = ContactMapping(
                contact_name=contact_name,
                user_id=user_id,
                contact_id=contact_id
            )
            
            self._mappings[contact_name] = mapping
            
            # 保存到配置文件
            if self._save_config():
                logger.info(f"[ContactUserMapper] ✓ 映射设置成功并已保存")
                return True
            else:
                logger.warning(f"[ContactUserMapper] ⚠ 映射已设置但保存失败")
                return False
                
        except Exception as e:
            logger.error(f"[ContactUserMapper] ✗ 设置映射失败: {e}")
            return False
    
    def _save_config(self) -> bool:
        """
        保存配置到文件
        
        Returns:
            是否保存成功
        """
        logger.debug(f"[ContactUserMapper] 保存配置到文件: {self.config_file}")
        
        try:
            config_data = {
                "contact_mappings": {},
                # default_user_id 已弃用，不再写入配置文件
                "enabled_contacts": self.enabled_contacts
            }
            
            # 转换映射数据
            for contact_name, mapping in self._mappings.items():
                if mapping.contact_id:
                    config_data["contact_mappings"][contact_name] = {
                        "user_id": mapping.user_id,
                        "contact_id": mapping.contact_id
                    }
                else:
                    config_data["contact_mappings"][contact_name] = mapping.user_id
            
            # 确保目录存在
            self.config_file.parent.mkdir(parents=True, exist_ok=True)
            
            # 写入文件
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(config_data, f, ensure_ascii=False, indent=2)
            
            logger.debug(f"[ContactUserMapper] ✓ 配置文件保存成功")
            return True
            
        except Exception as e:
            logger.error(f"[ContactUserMapper] ✗ 保存配置文件失败: {e}")
            return False
    
    def get_all_contacts(self) -> List[str]:
        """
        获取所有已配置的联系人列表
        
        Returns:
            联系人名称列表
        """
        contacts = list(self._mappings.keys())
        logger.debug(f"[ContactUserMapper] 获取所有联系人: {len(contacts)} 个")
        return contacts
    
    def get_enabled_contacts(self) -> List[str]:
        """
        获取启用的联系人列表
        
        Returns:
            启用的联系人名称列表
        """
        if not self.enabled_contacts:
            # 空列表表示所有联系人
            contacts = list(self._mappings.keys())
            logger.debug(f"[ContactUserMapper] 所有联系人均启用: {len(contacts)} 个")
            return contacts
        
        enabled = [c for c in self.enabled_contacts if c in self._mappings]
        logger.debug(f"[ContactUserMapper] 启用的联系人: {len(enabled)} 个")
        return enabled

    def _load_me_contact_from_env(self) -> None:
        """
        从环境变量加载“我”联系人配置。

        约定：
        - WECHAT_ME_CONTACT：优先使用
        - WECHAT_ME_CONTACT_NAME：备用

        若环境变量指定的联系人不在 contact_mappings 中，会记录 warning，但仍保留该名称，方便后续按名称做过滤。
        """
        # 优先 WECHAT_ME_CONTACT，其次 WECHAT_ME_CONTACT_NAME
        name = os.environ.get("WECHAT_ME_CONTACT") or os.environ.get("WECHAT_ME_CONTACT_NAME")
        if not name:
            return
        name = name.strip()
        if not name:
            return

        self.me_contact_name = name

        if name not in self._mappings:
            logger.warning(
                "[ContactUserMapper] 环境变量指定的 me 联系人 '%s' 不在 contact_mappings 中，请检查配置",
                name,
            )
        else:
            logger.info("[ContactUserMapper] 已通过环境变量配置 me 联系人: %s", name)

    def get_me_contact_name(self) -> Optional[str]:
        """
        获取通过环境变量配置的“我”联系人名称（如果未配置则返回 None）
        """
        return self.me_contact_name
    
    def is_contact_enabled(self, contact_name: str) -> bool:
        """
        检查联系人是否启用
        
        Args:
            contact_name: 联系人名称
        
        Returns:
            是否启用
        """
        if not self.enabled_contacts:
            # 空列表表示所有联系人都启用
            return True
        
        enabled = contact_name in self.enabled_contacts
        logger.debug(f"[ContactUserMapper] 联系人 {contact_name} 启用状态: {enabled}")
        return enabled


def get_global_mapper() -> ContactUserMapper:
    """
    获取全局单例的 ContactUserMapper 实例
    
    Returns:
        全局 ContactUserMapper 实例
    """
    global _global_mapper_instance
    if _global_mapper_instance is None:
        _global_mapper_instance = ContactUserMapper()
        logger.info(f"[ContactUserMapper] 创建全局单例实例，已加载 {len(_global_mapper_instance._mappings)} 个映射")
    return _global_mapper_instance
